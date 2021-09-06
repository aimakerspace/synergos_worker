#!/usr/bin/env python

"""
Remember to assign all configurable variables in CAPS (eg. OUT_DIR).
This is because Flask-restx will only load all uppercase variables from
`config.py`.
"""

####################
# Required Modules #
####################

# Generic
import json
import logging
import os
import random
import subprocess
import sys
import threading
import zipfile
from collections import defaultdict, OrderedDict
from glob import glob
from multiprocessing import Manager
from pathlib import Path
from string import Template
from typing import Dict

# Libs
import numpy as np
import psutil
import torch as th

# Custom
from synlogger.general import WorkerLogger, SysmetricLogger

##################
# Configurations #
##################

SRC_DIR = Path(__file__).parent.absolute()

API_VERSION = "0.1.0"

infinite_nested_dict = lambda: defaultdict(infinite_nested_dict)

####################
# Helper Functions #
####################

def seed_everything(seed: int = 42) -> bool:
    """ Convenience function to set a constant random seed for model consistency

    Args:
        seed (int): Seed for RNG
    Returns:
        True    if operation is successful
        False   otherwise
    """
    try:
        random.seed(seed)
        th.manual_seed(seed)
        th.cuda.manual_seed_all(seed)
        np.random.seed(seed)
        os.environ['PYTHONHASHSEED'] = str(seed)
        return True

    except:
        return False


def count_available_cpus(safe_mode: bool = False, r_count: int = 1) -> int:
    """ Counts no. of detected CPUs in the current system. By default, all 
        CPU cores detected are returned. However, if safe mode is toggled, then
        a specified number of cores are reserved.
    
    Args:
        safe_mode (bool): Toggles if cores are reserved
        r_count (int): No. of cores to reserve
    Return:
        No. of usable cores (int)
    """
    total_cores_available = psutil.cpu_count(logical=True)
    reserved_cores = safe_mode * r_count
    return total_cores_available - reserved_cores


def count_available_gpus() -> int:
    """ Counts no. of attached GPUs devices in the current system. As GPU 
        support is supplimentary, if any exceptions are caught here, system
        defaults back to CPU-driven processes (i.e. gpu count is 0)

    Returns:
        gpu_count (int)
    """
    try:
        process = subprocess.run(
            ['lspci'],
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True
        )
        all_detected_devices = process.stdout.split('\n')
        gpus = [
            device 
            for device in all_detected_devices 
            if (('VGA' in device) or ('Display' in device)) and
            'Integrated Graphics' not in device # exclude integrated graphics
        ]
        logging.debug(f"Detected GPUs: {gpus}")
        return len(gpus)

    except subprocess.CalledProcessError as cpe:
        logging.warning(f"Could not detect GPUs! Error: {cpe}")
        logging.warning(f"Defaulting to CPU processing instead...")
        return 0


def detect_configurations(dirname: str) -> Dict[str, str]:
    """ Automates loading of configuration files in specified directory

    Args:
        dirname (str): Target directory to load configurations from
    Returns:
        Params (dict)
    """

    def parse_filename(filepath: str) -> str:
        """ Extracts filename from a specified filepath
            Assumptions: There are no '.' in filename
        
        Args:
            filepath (str): Path of file to parse
        Returns:
            filename (str)
        """
        return os.path.basename(filepath).split('.')[0]

    # Load in parameters for participating servers
    config_globstring = os.path.join(SRC_DIR, dirname, "*.json")
    config_paths = glob(config_globstring)

    return {parse_filename(c_path): c_path for c_path in config_paths}


def capture_system_snapshot() -> dict:
    """ Takes a snapshot of parameters used in system-wide operations

    Returns:
        System snapshot (dict)
    """
    return {
        'IS_MASTER': IS_MASTER,
        'IN_DIR': IN_DIR,
        'OUT_DIR': OUT_DIR,
        'DATA_DIR': DATA_DIR,
        'MODEL_DIR': MODEL_DIR,
        'CUSTOM_DIR': CUSTOM_DIR,
        'TEST_DIR': TEST_DIR,
        'CORES_USED': CORES_USED,
        'GPU_COUNT': GPU_COUNT,
        'DB_TEMPLATE': DB_TEMPLATE,
        'SCHEMAS': SCHEMAS,
        'CACHE_TEMPLATE': CACHE_TEMPLATE,
        'PREDICT_TEMPLATE': PREDICT_TEMPLATE
    }


def configure_cpu_allocation(**res_kwargs) -> int:
    """ Configures no. of CPU cores available to the system. By default, all
        CPU cores will be allocated.

    Args:
        res_kwargs: Any custom resource allocations declared by user
    Returns:
        CPU cores used (int) 
    """
    global CORES_USED
    cpu_count = res_kwargs.get('cpus')
    CORES_USED = min(cpu_count, CORES_USED) if cpu_count else CORES_USED
    return CORES_USED


def configure_gpu_allocation(**res_kwargs):
    """ Configures no. of GPU cores available to the system.

    Args:
        res_kwargs: Any custom resource allocations declared by user
    Returns:
        GPU cores used (int) 
    """
    global GPU_COUNT
    gpu_count = res_kwargs.get('gpus')
    GPU_COUNT = min(gpu_count, GPU_COUNT) if gpu_count else GPU_COUNT
    return GPU_COUNT


def configure_node_logger(**logger_kwargs) -> WorkerLogger:
    """ Initialises the synergos logger corresponding to the current node type.
        In this case, a WorkerLogger is initialised.

    Args:
        logger_kwargs: Any parameters required for node logger configuration
    Returns:
        Node logger (WorkerLogger)
    """
    global NODE_LOGGER
    NODE_LOGGER = WorkerLogger(**logger_kwargs)
    NODE_LOGGER.initialise()
    return NODE_LOGGER


def configure_sysmetric_logger(**logger_kwargs) -> SysmetricLogger:
    """ Initialises the sysmetric logger to facillitate polling for hardware
        statistics.

    Args:
        logger_kwargs: Any parameters required for node logger configuration
    Returns:
        Sysmetric logger (SysmetricLogger)
    """
    global SYSMETRIC_LOGGER
    SYSMETRIC_LOGGER = SysmetricLogger(**logger_kwargs)
    return SYSMETRIC_LOGGER


def install(package: str) -> bool:
    """ Allows for dynamic runtime installation of python modules. 
    
        IMPORTANT: 
        Modules specified will be installed from source, meaning that `package` 
        must be a path to some `.tar.gz` archive.

    Args:
        package (str): Path to distribution package for installation
    """
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        return True

    except:
        return False

##################################################
# Synergos Worker Container Local Configurations #
##################################################
""" 
General parameters required for processing inputs & outputs
"""
# Define server's role: Master or slave
IS_MASTER = False

# State input directory
IN_DIR = os.path.join(SRC_DIR, "inputs")

# State output directory
OUT_DIR = os.path.join(SRC_DIR, "outputs")

# State data directory
DATA_DIR = os.path.join(SRC_DIR, "data")

# State model directory
MODEL_DIR = os.path.join(SRC_DIR, "models")

# State custom directory
CUSTOM_DIR = os.path.join(SRC_DIR, "custom")

# State test directory
TEST_DIR = os.path.join(SRC_DIR, "tests")

# Initialise Cache
CACHE = infinite_nested_dict()

# Allocate no. of cores for processes
CORES_USED = count_available_cpus(safe_mode=True)

# Detect no. of GPUs attached to server
GPU_COUNT = count_available_gpus()

logging.debug(f"Is master node? {IS_MASTER}")
logging.debug(f"Input directory detected: {IN_DIR}")
logging.debug(f"Output directory detected: {OUT_DIR}")
logging.debug(f"Data directory detected: {DATA_DIR}")
logging.debug(f"Test directory detected: {TEST_DIR}")
logging.debug(f"Cache initialised: {CACHE}")
logging.debug(f"No. of available CPU Cores: {CORES_USED}")
logging.debug(f"No. of available GPUs: {GPU_COUNT}")

###########################################
# Synergos Worker Database Configurations #
###########################################
""" 
In Synergos Worker, the database is used mainly for caching results of 
operations triggered by the TTP's REST-RPC calls
"""
db_outpath = os.path.join(OUT_DIR, "$collab_id", "$project_id", "operations.json")
DB_TEMPLATE = Template(db_outpath)

logging.debug(f"Database template path detected: {DB_TEMPLATE}")

####################################
# Synergos Worker Template Schemas #
####################################
"""
For REST service to be stable, there must be schemas enforced to ensure that 
any erroneous queries will be rejected immediately, anf ultimately, not affect 
the functions of the system.
"""
template_paths = detect_configurations("templates")

SCHEMAS = {}
for name, s_path in template_paths.items():
    with open(s_path, 'r') as schema:
        SCHEMAS[name] = json.load(schema, object_pairs_hook=OrderedDict)

logging.debug(f"Schemas loaded: {list(SCHEMAS.keys())}")

######################################### 
# Synergos Worker Export Configurations #
######################################### 
"""
Certain Flask requests sent from the TTP (namely `/poll` and `/predict`) will
trigger file exports to the local machine, while other requests 
(i.e. `initialise`) perform lazy loading and require access to these exports.
This will ensure that all exported filenames are consistent during referencing.
"""
cache_dir = os.path.join(OUT_DIR, "$collab_id", "$project_id", "preprocessing")
aggregated_X_outpath = os.path.join(cache_dir, "preprocessed_X_$meta.npy")
aggregated_y_outpath = os.path.join(cache_dir, "preprocessed_y_$meta.npy")
aggregated_df_outpath = os.path.join(cache_dir, "combined_dataframe_$meta.csv")
catalogue_outpath = os.path.join(cache_dir, "catalogue.json")
CACHE_TEMPLATE = {
    'out_dir': Template(cache_dir),
    'X': Template(aggregated_X_outpath),
    'y': Template(aggregated_y_outpath),
    'dataframe': Template(aggregated_df_outpath),
    'catalogue': Template(catalogue_outpath)
}

predict_outdir = os.path.join(
    OUT_DIR, 
    "$collab_id",
    "$project_id", 
    "$expt_id", 
    "$run_id", 
    "$meta"
)
y_pred_outpath = os.path.join(predict_outdir, "inference_predictions_$meta.txt")
y_score_outpath = os.path.join(predict_outdir, "inference_scores_$meta.txt")
stats_outpath = os.path.join(predict_outdir, "inference_statistics_$meta.json")
PREDICT_TEMPLATE = {
    'out_dir': Template(predict_outdir),
    'y_pred': Template(y_pred_outpath),
    'y_score': Template(y_score_outpath),
    'statistics': Template(stats_outpath)
}

###############################################
# Synergos Worker REST Payload Configurations #
###############################################
"""
Responses for REST-RPC have a specific format to allow compatibility between 
TTP & Worker Flask Interfaces. Remember to modify rest_rpc.connection.core.utils.Payload 
upon modifying this template!
"""
PAYLOAD_TEMPLATE = {
    'apiVersion': API_VERSION,
    'success': 0,
    'status': None,
    'method': "",
    'params': {},
    'data': {}
}

##########################################
# Synergos Worker Logging Configurations #
##########################################
"""
Synergos has certain optional components, such as a centrialised logging 
server, as well as a metadata catalogue. This section governs configuration of 
the worker node to facilitate such integrations, where applicable. This portion
gets configured during runtime.
"""
NODE_LOGGER = None
SYSMETRIC_LOGGER = None

##################################################
# Synergos Worker Language Models Configurations #
##################################################
"""
NLP pipelines in Synergos are flexible in that different backends are 
supported. Users are free to mount language sources/dependencies for their
desired backends (should it be supported).
"""
# Install language models for Spacy
spacy_src_dir = Path(os.path.join(CUSTOM_DIR, 'spacy'))
spacy_sources = list(spacy_src_dir.glob('**/*.tar.gz'))
for sp_src in spacy_sources:
    install(sp_src)

# Load all user-declared source paths for Symspell
symspell_src_dir = Path(os.path.join(CUSTOM_DIR, 'symspell'))
SYMSPELL_DICTIONARIES = list(symspell_src_dir.glob('**/*dictionary*.txt'))
SYMSPELL_BIGRAMS = list(symspell_src_dir.glob('**/*bigram*.txt'))

# Load all user-declared data paths for NLTK
nltk_src_dir = os.path.join(CUSTOM_DIR, 'nltk_data')
os.environ["NLTK_DATA"] = nltk_src_dir
nltk_sources = list(Path(nltk_src_dir).glob('**/*.zip'))
for nltk_src in nltk_sources:
    with zipfile.ZipFile(nltk_src,"r") as zip_ref:
        zip_ref.extractall(path=nltk_src.parent)
