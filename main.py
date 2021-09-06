#!/usr/bin/env python

####################
# Required Modules #
####################

# Generic/Built-in
import argparse
import logging
import os
import uuid

# Libs
from waitress import serve

# Custom
from config import (
    capture_system_snapshot,
    configure_cpu_allocation,
    configure_gpu_allocation,
    configure_node_logger, 
    configure_sysmetric_logger
)

##################
# Configurations #
##################

SOURCE_FILE = os.path.abspath(__file__)

SECRET_KEY = "synergos_worker" # secret key

#############
# Functions #
#############

def construct_logger_kwargs(**kwargs) -> dict:
    """ Extracts user-parsed values and re-mapping them into parameters 
        corresponding to those required of components from Synergos Logger.

    Args:
        kwargs: Any user input captured 
    Returns:
        Logger configurations (dict)
    """
    logger_name = kwargs['id']

    logging_config = kwargs['logging_variant']

    logging_variant = logging_config[0]
    if logging_variant not in ["basic", "graylog"]:
        raise argparse.ArgumentTypeError(
            f"Specified variant '{logging_variant}' is not supported!"
        )

    server = (logging_config[1] if len(logging_config) > 1 else None)
    port = (int(logging_config[2]) if len(logging_config) > 1 else None)

    debug_mode = kwargs['debug']
    logging_level = logging.DEBUG if debug_mode else logging.INFO
    debugging_fields = debug_mode

    is_censored = kwargs['censored']
    censor_keys = (
        [
            'SRC_DIR', 'IN_DIR', 'OUT_DIR', 'DATA_DIR', 'MODEL_DIR', 
            'CUSTOM_DIR', 'TEST_DIR', 'DB_TEMPLATE', 'CACHE_TEMPLATE', 
            'PREDICT_TEMPLATE'
        ]
        if is_censored 
        else []
    )

    return {
        'logger_name': logger_name,
        'logging_variant': logging_variant,
        'server': server,
        'port': port,
        'logging_level': logging_level,
        'debugging_fields': debugging_fields,
        'censor_keys': censor_keys
    }


def construct_resource_kwargs(**kwargs) -> dict:
    """ Extracts user-parsed values and re-mapping them into parameters 
        corresponding to resource allocations

    Args:
        kwargs: Any user input captured 
    Returns:
        Resource configurations (dict)
    """
    cpus = kwargs['cpus']
    gpus = kwargs['gpus']
    return {'cpus': cpus, 'gpus': gpus}

###########
# Scripts #
###########

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(
        description="REST-RPC Receiver for a Synergos Network."
    )

    parser.add_argument(
        "--id",
        "-i",
        type=str,
        default=f"worker/{uuid.uuid4()}",
        help="ID of worker, e.g. --id Alice"
    )

    parser.add_argument(
        "--logging_variant",
        "-l",
        type=str,
        default="basic",
        nargs="+",
        help="Type of logging framework to use. eg. --logging_variant graylog 127.0.0.1 9400"
    )

    parser.add_argument(
        "--logging_resolution",
        "-r",
        type=int,
        help="Interval to wait before system usage is logged again"
    )   

    parser.add_argument(
        "--cpus",
        type=int,
        help="No. of CPU cores to allocate for this service. If not specified, auto-detect CPU count"
    )    

    parser.add_argument(
        "--gpus",
        type=int,
        help="No. of GPU cores to allocate for this service. If not specified, auto-detect GPU count"
    )   

    parser.add_argument(
        '--censored',
        "-c",
        action='store_true',
        default=False,
        help="Toggles censorship of potentially sensitive information on this worker node"
    )

    parser.add_argument(
        '--debug',
        "-d",
        action='store_true',
        default=False,
        help="Toggles debugging mode on this worker node"
    )

    input_kwargs = vars(parser.parse_args())
    system_kwargs = capture_system_snapshot()
    res_kwargs = construct_resource_kwargs(**input_kwargs)
    logger_kwargs = construct_logger_kwargs(**input_kwargs)

    configure_cpu_allocation(**res_kwargs)
    configure_gpu_allocation(**res_kwargs)

    server_id = input_kwargs['id']
    node_logger = configure_node_logger(**logger_kwargs)
    node_logger.synlog.info(
        f"Participant `{server_id}` -> Snapshot of Input Parameters",
        **input_kwargs
    )
    node_logger.synlog.info(
        f"Participant `{server_id}` -> Snapshot of System Parameters",
        **system_kwargs
    )
    node_logger.synlog.info(
        f"Participant `{server_id}` -> Snapshot of Logging Parameters",
        **logger_kwargs
    )

    sysmetric_logger = configure_sysmetric_logger(**logger_kwargs)
    sysmetric_logger.track(
        file_path=SOURCE_FILE,
        class_name="",
        function_name="",
        resolution=input_kwargs['logging_resolution']
    )

    try:

        ###########################
        # Implementation Footnote #
        ###########################

        # [Cause]
        # To allow custom Synergos Logging components to permeate the entire
        # system, these loggers have to be initialised first before the system
        # performs module loading. 

        # [Problems]
        # Importing app right at the start of the page causes system modules to
        # be loaded first, resulting in AttributeErrors, since 
        # synlogger.general.WorkerLogger has not been intialised, and thus, its
        # corresponding `synlog` attribute cannot be referenced.

        # [Solution]
        # Import system modules only after loggers have been intialised.

        from rest_rpc import app       
        serve(app, host='0.0.0.0', port=5000)

    finally:
        sysmetric_logger.terminate()

