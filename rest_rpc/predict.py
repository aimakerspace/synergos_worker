####################
# Required Modules #
####################

# Generic/Built-in
import json
import logging
import os
from pathlib import Path

# Libs
import jsonschema
import numpy as np
from flask import request
from flask_restx import Namespace, Resource, fields

# Custom
from rest_rpc import app
from rest_rpc.core.utils import (
    Payload, 
    MetaRecords, 
    Benchmarker, 
    construct_combination_key
)
from rest_rpc.initialise import cache
from rest_rpc.align import alignment_model

##################
# Configurations #
##################

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.DEBUG)

ns_api = Namespace(
    "predict", 
    description='API to faciliate federated inference for participant.'
)

out_dir = app.config['OUT_DIR']

db_path = app.config['DB_PATH']
meta_records = MetaRecords(db_path=db_path)

###########################################################
# Models - Used for marshalling (i.e. moulding responses) #
###########################################################

# Marshalling Inputs
prediction_tags_model = ns_api.model(
    name="prediction_tags",
    model={
        'data': fields.Integer(required=True),
        'labels': fields.Integer(required=True),
        'outputs': fields.Integer(required=True),
        'predictions': fields.Integer(required=True)
    }
)

prediction_input_model = ns_api.model(
    name="prediction_input",
    model={
        'alignments': fields.Nested(alignment_model, required=True),
        'id_mappings': fields.List(fields.Nested(
            prediction_tags_model,
            required=True
        ))
    }
)

# Marshalling Outputs
stats_model = ns_api.model(
    name="statistics",
    model={
        'accuracy': fields.Float(),
        'roc_auc_score': fields.Float(),
        'pr_auc_score': fields.Float(),
        'f_score': fields.Float(),
        'TPR': fields.Float(),
        'TNR': fields.Float(),
        'PPV': fields.Float(),
        'NPV': fields.Float(),
        'FPR': fields.Float(),
        'FNR': fields.Float(),
        'FDR': fields.Float(),
        'TP': fields.Integer(),
        'TN': fields.Integer(),
        'FP': fields.Integer(),
        'FN': fields.Integer()
    }
)

meta_stats_model = ns_api.model(
    name="meta_statistics",
    model={
        'statistics': fields.Nested(stats_model, skip_none=True),
        'res_path': fields.String(skip_none=True)
    }
)

inferences_model = ns_api.model(
    name="inferences",
    model={
        'train': fields.Nested(meta_stats_model, skip_none=True),
        'evaluate': fields.Nested(meta_stats_model, skip_none=True),
        'predict': fields.Nested(meta_stats_model, skip_none=True)
    }
)

combination_field = fields.Wildcard(fields.Nested(inferences_model))
combination_model = ns_api.model(
    name="combination",
    model={"*": combination_field}
)

results_model = ns_api.model(
    name="results",
    model={
        'results': fields.Nested(combination_model, required=True)
    }
)

prediction_output_model = ns_api.inherit(
    "prediction_output",
    results_model,
    {
        'doc_id': fields.String(),
        'kind': fields.String(),
        'key': fields.Nested(
            ns_api.model(
                name='key',
                model={
                    'project_id': fields.String(),
                    'expt_id': fields.String(),
                    'run_id': fields.String()
                }
            ),
            required=True
        )
    }
)

payload_formatter = Payload('Predict', ns_api, prediction_output_model)

#############
# Resources #
#############

@ns_api.route('/<project_id>/<expt_id>/<run_id>')
@ns_api.response(200, 'Predictions cached successfully')
@ns_api.response(404, "Project logs has not been initialised")
@ns_api.response(417, "Insufficient info specified for auto-assembly")
@ns_api.response(500, "Internal failure")
class Prediction(Resource):

    @ns_api.doc("predict_data")
    # @ns_api.expect(prediction_input_model)
    @ns_api.marshal_with(payload_formatter.singular_model)
    def post(self, project_id, expt_id, run_id):
        """ Receives and reconstructs test dataset to pair with prediction 
            labels yielded from federated inference, and export the aligned
            prediction sets to file, before returning the computed statistics.

            Assumption: 
            Worker's server parameters & tags of registered datasets have 
            already be uploaded to TTP. This ensures that the TTP has the 
            feature alignment, as well as contact the respective workers 
            involved post-alignment.  

            JSON received will contain the following information:
            1) Inference (dict(str, dict(str, list(List(str)))) where
               list(list(str) is the string representation of a numpy array) 

            eg.

            {
                "inferences": {
                    "train": {},
                    "evaluate": {
                        "y_pred": [
                            [0.],
                            [1.],
                            [0.],
                            [1.],
                            .
                            .
                            .
                        ],
                        "y_score": [
                            [0.4561681891162],
                            [0.8616516118919],
                            [0.3218971919191],
                            [0.6919811999489],
                            .
                            .
                            .
                        ]
                    },
                    "predict": {
                        "y_pred": [
                            [1.],
                            [0.],
                            [1.],
                            [0.],
                            .
                            .
                            .
                        ],
                        "y_score": [
                            [0.9949189651566],
                            [0.1891929789119],
                            [0.7651658777992],
                            [0.4919196689197],
                            .
                            .
                            .
                        ]
                    }
                }
            }
        """
        expt_run_key = construct_combination_key(expt_id, run_id)

        # Search local database for cached operations
        retrieved_metadata = meta_records.read(project_id)
        
        if (retrieved_metadata and 
            expt_run_key in retrieved_metadata['in_progress']):

            # Assumption: 
            # When inference is in progress, WSSW object is active & is stored
            # in cache for retrieval/operation
            wss_worker = cache[project_id]['participant']

            logging.debug(f"Objects in WSSW: {wss_worker._objects}")
            logging.debug(f"Objects in hook: {wss_worker.hook.local_worker._objects}")

            # try:
            results = {}
            for meta, inference in request.json['inferences'].items():

                if inference:

                    logging.debug(f"Inference: {inference}")
                    # Prepare output directory for tensor export
                    meta_out_dir = os.path.join(
                        out_dir, 
                        project_id, 
                        expt_id,
                        run_id,
                        meta
                    )
                    os.makedirs(meta_out_dir, exist_ok=True)

                    # Convert received outputs into a compatible format
                    y_pred = np.array(inference['y_pred'])
                    y_score = np.array(inference['y_score'])

                    # Retrieved aligned y_true labels
                    path_to_labels = retrieved_metadata['exports'][meta]['y']
                    with open(path_to_labels, 'rb') as yep:
                        labels = np.load(yep)
                    loaded_labels = wss_worker.search(["#y", f"#{meta}"])[0].numpy()

                    logging.debug(f"y_pred: {y_pred}")
                    logging.debug(f"Labels: {labels}")
                    logging.debug(f"Loaded Labels: {loaded_labels}")

                    assert (labels == loaded_labels).all()

                    # Calculate inference statistics
                    benchmarker = Benchmarker(labels, y_pred, y_score)
                    statistics = benchmarker.calculate_stats()

                    # Export predictions & scores for client's reference
                    y_pred_export_path = os.path.join(
                        meta_out_dir, 
                        f"inference_predictions_{meta}.txt"
                    )
                    with open(y_pred_export_path, 'w') as ypep:
                        np.savetxt(ypep, y_pred)

                    y_score_export_path = os.path.join(
                        meta_out_dir, 
                        f"inference_scores_{meta}.txt"
                    )
                    with open(y_score_export_path, 'w') as ysep:
                        np.savetxt(ysep, y_score)

                    # Export benchmark statistics for client's reference
                    stats_export_path = os.path.join(
                        meta_out_dir,
                        f"inference_statistics_{meta}.json"
                    )
                    with open(stats_export_path, 'w') as sep:
                        json.dump(statistics, sep)

                    results[meta] = {
                        'statistics': statistics,
                        'res_path': stats_export_path
                    }

                    # Update relevant `exports` entries
                    retrieved_metadata['exports'][meta]['predictions'] = y_pred_export_path
                    retrieved_metadata['exports'][meta]['scores'] = y_score_export_path

            # Update relevant `results` entries 
            # Note: This will overwrite previous predictions
            retrieved_metadata['results'][expt_run_key] = results 
            updated_metadata = meta_records.update(
                project_id=project_id, 
                updates=retrieved_metadata
            )
            
            logging.debug(f"Updated Metadata: {updated_metadata}")

            success_payload = payload_formatter.construct_success_payload(
                status=200,
                method="predict.post",
                params=request.view_args,
                data=updated_metadata
            )
            return success_payload, 200

            # except KeyError as k:
            #     logging.debug(f"{k}")
            #     ns_api.abort(                
            #         code=417,
            #         message="Insufficient info specified for metadata tracing!"
            #     )

        else:
            ns_api.abort(
                code=404, 
                message=f"Project logs '{project_id}' has not been initialised! Please initialise and try again."
            )