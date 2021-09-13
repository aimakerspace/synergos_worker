#!/usr/bin/env python

####################
# Required Modules #
####################

# Generic/Built-in
import logging
import os

# Libs
from flask import request
from flask_restx import Namespace, Resource

# Custom
from rest_rpc import app
from rest_rpc.core.server import load_metadata_records
from rest_rpc.core.utils import Payload
from rest_rpc.initialise import cache, init_output_model

##################
# Configurations #
##################

SOURCE_FILE = os.path.abspath(__file__)

ns_api = Namespace(
    "terminate", 
    description='API to faciliate WSSW termination for participant.'
)

logging = app.config['NODE_LOGGER'].synlog
logging.debug("terminate.py logged", Description="No Changes")

###########################################################
# Models - Used for marshalling (i.e. moulding responses) #
###########################################################

# Imported from initialise.py

payload_formatter = Payload('Terminate', ns_api, init_output_model)

#############
# Resources #
#############

@ns_api.route('/<collab_id>/<project_id>/<expt_id>/<run_id>')
@ns_api.response(200, "WSSW object successfully terminated")
@ns_api.response(404, "WSSW object not found")
@ns_api.response(500, 'Internal failure')
class Termination(Resource):

    @ns_api.doc("terminate_wssw")
    @ns_api.marshal_with(payload_formatter.singular_model)
    def post(self, collab_id, project_id, expt_id, run_id):
        """ Closes WebsocketServerWorker to prevent potential cyber attacks during
            times of inactivity

            JSON received will contain the following information:
            1) Connections

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
                }
            }
        """
        # Search local database for cached operations
        meta_records = load_metadata_records(keys=request.view_args)
        retrieved_metadata = meta_records.read(project_id)

        if retrieved_metadata:

            project = cache.pop(project_id)
            wssw_process = project['process']
            wss_worker = project['participant']

            wss_worker.remove_worker_from_local_worker_registry()

            if wss_worker.loop.is_running():
                wss_worker.loop.call_soon_threadsafe(
                    wss_worker.loop.stop
                ).call_soon_threadsafe(
                    wss_worker.loop.close
                )
                assert not wss_worker.loop.is_running()
                
            if wssw_process.is_alive():
                wssw_process.terminate()    # end the process
                wssw_process.join()         # reclaim resources from thread   

                logging.info(
                    f"WSSW process {wssw_process.pid} has been terminated.",
                    wssw_process_id=wssw_process.pid,
                    ID_path=SOURCE_FILE,
                    ID_class=Termination.__name__, 
                    ID_function=Termination.post.__name__,
                    **request.view_args
                )
                logging.info(
                    f"Terminated process exitcode: {wssw_process.exitcode}", 
                    wssw_process_exitcode=wssw_process.exitcode,
                    ID_path=SOURCE_FILE,
                    ID_class=Termination.__name__, 
                    ID_function=Termination.post.__name__,
                    **request.view_args
                )
                
                assert not wssw_process.is_alive()
                wssw_process.close()        # release resources immediately

            retrieved_metadata['is_live'] = False

            logging.info(
                f"Termination - Current state of Cache tracked.", 
                cache=cache,
                ID_path=SOURCE_FILE,
                ID_class=Termination.__name__, 
                ID_function=Termination.post.__name__,
                **request.view_args
            )

            updated_metadata = meta_records.update(
                project_id=project_id, 
                updates=retrieved_metadata
            )

            success_payload = payload_formatter.construct_success_payload(
                status=200,
                method="terminate.post",
                params=request.view_args,
                data=updated_metadata
            )
            logging.info(
                "Federated cycle successfully initialised!", 
                code="200", 
                ID_path=SOURCE_FILE,
                ID_class=Termination.__name__, 
                ID_function=Termination.post.__name__,
                **request.view_args
            )
            return success_payload, 200

        else:
            logging.error(
                f"Project not yet initialised", 
                code="404", 
                description=f"Project logs '{project_id}' has not been initialised! Please poll and try again.", 
                Class=Termination.__name__, 
                function=Termination.post.__name__
            )
            ns_api.abort(
                code=404, 
                message=f"Project '{project_id}' has not been initialised! Please poll and try again."
            )
