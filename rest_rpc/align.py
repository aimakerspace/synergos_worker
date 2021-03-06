#!/usr/bin/env python

####################
# Required Modules #
####################

# Generic/Built-in
import os
from pathlib import Path

# Libs
from flask import request
from flask_restx import Namespace, Resource, fields

# Custom
from rest_rpc import app
from rest_rpc.core.server import load_metadata_records
from rest_rpc.core.utils import Payload
from rest_rpc.poll import poll_input_model

##################
# Configurations #
##################

SOURCE_FILE = os.path.abspath(__file__)

ns_api = Namespace(
    "align", 
    description='API to faciliate metadata retrieval from participant.'
)

logging = app.config['NODE_LOGGER'].synlog
logging.debug("align.py logged", Description="No Changes")

###########################################################
# Models - Used for marshalling (i.e. moulding responses) #
###########################################################

xy_alignment_model = ns_api.model(
    name="xy_alignments",
    model={
        'X': fields.List(fields.Integer(), required=True),
        'y': fields.List(fields.Integer(), required=True)
    }
)

alignment_model = ns_api.model(
    name="alignments",
    model={
        'train': fields.Nested(xy_alignment_model),
        'evaluate': fields.Nested(xy_alignment_model),
        'predict': fields.Nested(xy_alignment_model),
    }
)

# Marshalling Inputs
alignment_input_model = ns_api.inherit(
    "alignment_input",
    poll_input_model,
    {
        'alignments': fields.Nested(alignment_model, required=True)
    }
)

# Marshalling outputs
alignment_output_model = ns_api.model(
    name="alignment_output",
    model={
        'doc_id': fields.String(),
        'kind': fields.String(),
        'key': fields.Nested(
            ns_api.model(
                name='key',
                model={
                    'project_id': fields.String()
                }
            ),
            required=True
        ),
        'alignments': fields.Nested(alignment_model, required=True)
    }
)

payload_formatter = Payload('Align', ns_api, alignment_output_model)

#############
# Resources #
#############

@ns_api.route('/<collab_id>/<project_id>')
@ns_api.response(200, 'Alignments cached successfully')
@ns_api.response(404, "Project logs has not been initialised")
@ns_api.response(417, "Insufficient info specified for data alignment")
@ns_api.response(500, "Internal failure")
class Alignment(Resource):

    @ns_api.doc("poll_metadata")
    @ns_api.expect(alignment_input_model)
    @ns_api.marshal_with(payload_formatter.singular_model)
    def post(self, collab_id, project_id):
        """ Receives and caches the null indexes to be populated within the 
            worker's registered datasets in order for them to have the same 
            schema as all other participants

            Assumption: 
            Worker's server parameters & tags of registered datasets have 
            already be uploaded to TTP. This ensures that the TTP has the 
            feature alignment, as well as contact the respective workers 
            involved post-alignment.  

            JSON received will contain the following information:
            1) Connections
            2) Data tags
            3) Indexes to insert null representation of columns on

            eg. 

            {
                "connections": {
                    'logs': {
                        'host': "172.18.0.4",
                        'port': 5000,
                        'configurations': {
                            name: "test_participant_1",
                            logging_level: 20,
                            logging_variant: "graylog",
                            debugging_fields: False,
                        }
                    }
                },
                "tags": {
                    "train": [["type_a","v1"], ["type_b","v2"]],
                    "evaluate": [["type_c","v3"]]
                },
                "alignments": {
                    "train": {
                        "X": [0,1,3,6,8],
                        "y": [1]
                    },
                    "evaluate": {
                        "X": [0,1,3,6,8,9],
                        "y": [2],
                    }
                }
            }

            This data will be cached in the worker database for subsequent use.
        """
        # Search local database for cached operations
        meta_records = load_metadata_records(keys=request.view_args)
        retrieved_metadata = meta_records.read(project_id)
        
        if retrieved_metadata:
            try:
                assert request.json['tags'] == retrieved_metadata['tags']
                alignments = request.json['alignments']
                retrieved_metadata['alignments'] = alignments

                updated_metadata = meta_records.update(
                    project_id=project_id, 
                    updates=retrieved_metadata
                )

                success_payload = payload_formatter.construct_success_payload(
                    status=200,
                    method="align.post",
                    params=request.view_args,
                    data=updated_metadata
                )
                logging.info(
                    f"Alignments successfully archived!",
                    status="200",
                    ID_path=SOURCE_FILE,
                    ID_class=Alignment.__name__, 
                    ID_function=Alignment.post.__name__,
                    **request.view_args
                )
                return success_payload, 200

            except KeyError:
                logging.error(
                    f"Project not yet initialised!",  
                    code="404", 
                    description=f"Project logs '{project_id}' has not been initialised! Please poll and try again.",
                    ID_path=SOURCE_FILE,
                    ID_class=Alignment.__name__, 
                    ID_function=Alignment.post.__name__,
                    **request.view_args
                )
                ns_api.abort(
                    code=404, 
                    message=f"Project logs '{project_id}' has not been initialised! Please poll and try again."
                )  

        else:
            logging.error(
                f"Project not yet initialised!", 
                code="404", 
                description=f"Project logs '{project_id}' has not been initialised! Please poll and try again.", 
                ID_path=SOURCE_FILE,
                ID_class=Alignment.__name__, 
                ID_function=Alignment.post.__name__,
                **request.view_args
            )
            ns_api.abort(
                code=404, 
                message=f"Project logs '{project_id}' has not been initialised! Please poll and try again."
            )