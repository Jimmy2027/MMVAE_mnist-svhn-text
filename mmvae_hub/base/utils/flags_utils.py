# -*- coding: utf-8 -*-
import argparse
import json
import os
from abc import abstractmethod
from pathlib import Path

import numpy as np
import torch
from mmvae_hub.base import log
from mmvae_hub.base.utils.filehandling import get_method, create_dir_structure


class BaseFlagsSetup:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.parser = None

    def setup(self, flags, testing=False):
        """
        Setup the flags:
            - update_flags_with_config
            - expand user in paths and set paths if not given
            - set device
            - set alpha modalities
            - set len_sequence
            - load flags
            - set seed
        """
        if not flags.dir_fid:
            flags.dir_fid = flags.dir_experiment
        flags.config_path = self.config_path
        if self.config_path:
            flags = update_flags_with_config(p=self.parser, config_path=flags.config_path, testing=testing)
        flags = self.setup_paths(flags)
        flags = create_dir_structure(flags)
        use_cuda = torch.cuda.is_available()
        flags.device = torch.device('cuda' if use_cuda else 'cpu')
        if str(flags.device) == 'cuda':
            torch.cuda.set_device(get_freer_gpu())
        flags = self.flags_set_alpha_modalities(flags)
        flags.log_file = log.manager.root.handlers[1].baseFilename
        flags.len_sequence = 128 if flags.text_encoding == 'word' else 1024

        if flags.load_flags:
            old_flags = torch.load(Path(flags.load_flags).expanduser())
            # create param dict from all the params of old_flags that are not paths
            params = {k: v for k, v in old_flags.item() if ('dir' not in v) and ('path' not in v)}
            flags.__dict__.update(params)

        if not flags.seed:
            # set a random seed
            flags.seed = np.random.randint(0, 10000)
        flags = get_method(flags)
        return flags

    @abstractmethod
    def flags_set_alpha_modalities(self, flags):
        pass

    def setup_paths(self, flags: argparse.ArgumentParser()) -> argparse.ArgumentParser():
        """Expand user in paths and set dir_fid if not given."""
        flags.dir_data = Path(flags.dir_data).expanduser()
        flags.dir_experiment = Path(flags.dir_experiment).expanduser()
        flags.inception_state_dict = Path(flags.inception_state_dict).expanduser()
        flags.dir_fid = Path(flags.dir_fid).expanduser() if flags.dir_fid else flags.dir_experiment / 'fid'
        flags.dir_clf = Path(flags.dir_clf).expanduser() if flags.use_clf else None
        return flags


def get_freer_gpu():
    """
    Returns the index of the gpu with the most free memory.
    Taken from https://discuss.pytorch.org/t/it-there-anyway-to-let-program-select-free-gpu-automatically/17560/6
    """
    os.system('nvidia-smi -q -d Memory |grep -A4 GPU|grep Free >tmp')
    memory_available = [int(x.split()[2]) for x in open('tmp', 'r').readlines()]
    return np.argmax(memory_available)


def update_flags_with_config(p, config_path: Path, additional_args: dict = None, testing=False):
    """
    If testing is true, no cli arguments will be read.

    Parameters
    ----------
    p : parser to be updated.
    config_path : path to the json config file.
    additional_args : optional additional arguments to be passed as dict.
    """
    additional_args = additional_args or {}
    with open(config_path, 'rt') as json_file:
        t_args = argparse.Namespace()
        json_config = json.load(json_file)
    t_args.__dict__.update({**json_config, **additional_args})
    if testing:
        return p.parse_args([], namespace=t_args)
    else:
        return p.parse_args(namespace=t_args)