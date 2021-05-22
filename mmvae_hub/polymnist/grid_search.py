from norby.utils import norby
from sklearn.model_selection import ParameterGrid

from mmvae_hub.base.utils.flags_utils import get_config_path
from mmvae_hub.polymnist import PolymnistTrainer
from mmvae_hub.polymnist.experiment import PolymnistExperiment
from mmvae_hub.polymnist.flags import FlagsSetup, parser

search_spaces = {
    # 'method': ['pfom'],
    'method': ['planar_mixture'],
    # 'method': ['joint_elbo'],
    'class_dim': [512],
    "beta": [2.5],
    "num_flows": [5],
    "num_mods": [3],
    "end_epoch": [100],
    "weighted_mixture": [False]
}

search_spaces_1 = {
    'method': ['pfom'],
    # 'method': ['moe'],
    'class_dim': [512],
    "beta": [1],
    "num_flows": [5],
    "num_mods": [3],
    "end_epoch": [100],
    "weighted_mixture": [True]
}

if __name__ == '__main__':

    for grid in [search_spaces_1]:
        for sp in ParameterGrid(grid):
            # for _ in [1]:
            flags = parser.parse_args()
            flags_setup = FlagsSetup(get_config_path(flags))
            flags = flags_setup.setup(flags, additional_args=sp)
            with norby(f'Starting Experiment {flags.experiment_uid}.', f'Experiment {flags.experiment_uid} finished.'):
                # if True:
                # flags = flags_setup.setup(flags)
                mst = PolymnistExperiment(flags)
                mst.set_optimizer()
                trainer = PolymnistTrainer(mst)
                trainer.run_epochs()

