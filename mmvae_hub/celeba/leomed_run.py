# -*- coding: utf-8 -*-
from sklearn.model_selection import ParameterGrid

from mmvae_hub.hyperopt.search_spaces.search_spaces import *
from mmvae_hub.leomed_utils.launch_jobs import launch_leomed_jobs

# for search_space in [iwmogfm2]:
# for search_space in [sp_mofop]:
# for search_space in [mopgfm_celeba, mopoe_celeba]:
for search_space in [mopoe_celeba]:
    # for search_space in [search_space_je, search_space_gfm, search_space_mofop]:

    for params in ParameterGrid(search_space):
        params["eval_freq"] = 50
        launch_leomed_jobs(which_dataset='celeba', params=params)
