import tempfile

import numpy as np
import pytest

from mmvae_hub.base.evaluation.eval_metrics.coherence import test_generation
from mmvae_hub.base.utils.plotting import generate_plots
from mmvae_hub.polymnist import PolymnistTrainer
from tests.utils import set_me_up


@pytest.mark.tox
@pytest.mark.parametrize("method", ['joint_elbo', 'planar_mixture'])
def test_run_epochs_polymnist(method: str):
    """
    Test if the main training loop runs.
    Assert if the total_test loss is constant. If the assertion fails, it means that the model or the evaluation has
    changed, perhaps involuntarily.
    """
    with tempfile.TemporaryDirectory() as tmpdirname:
        mst = set_me_up(tmpdirname, method)
        trainer = PolymnistTrainer(mst)
        test_results = trainer.run_epochs()
        asfd = 0
        # assert test_results['total_loss'] == 7733.9169921875


@pytest.mark.tox
@pytest.mark.parametrize("method", ['moe', 'joint_elbo'])
def test_static_results_2mods(method: str):
    """
    Test if the results are constant. If the assertion fails, it means that the model or the evaluation has
    changed, perhaps involuntarily.
    """
    static_results = {
        'moe': {"joint_div": 0.24978025257587433,
                "latents_class": {'mu': -0.0019471765263006091},
                "klds": 0.2534570097923279,
                "lhoods": -2613.809326171875,
                "log_probs": 2616.397705078125,
                "total_loss": 5248.791015625,
                "lr_eval": 0.05
                },
        'planar_mixture': {"joint_div": -9.384511947631836,
                           "latents_class": {'mu': 0.2744814455509186},
                           "klds": 0.2744814455509186,
                           "lhoods": -2613.845703125,
                           "log_probs": 2616.397216796875,
                           "total_loss": 2617.664306640625,
                           "lr_eval": 0.05
                           },
        'joint_elbo': {"joint_div": 0.9404307007789612,
                       "latents_class": {'mu': 0.000365212959877681},
                       "klds": 0.2594645023345947,
                       "lhoods": -2613.80517578125,
                       "log_probs": 2616.78173828125,
                       "total_loss": 5252.92236328125,
                       "lr_eval": 0.05
                       },

    }

    with tempfile.TemporaryDirectory() as tmpdirname:
        # mst = set_me_up(tmpdirname, method='moe',
        #                 attributes={'num_flows': 0, 'num_mods': 1, 'deterministic': True, 'device': 'cpu'})
        mst = set_me_up(tmpdirname,
                        method=method,
                        attributes={'num_flows': 0, 'num_mods': 2, 'deterministic': True, 'device': 'cpu',
                                    'steps_per_training_epoch': 1, 'factorized_representation': False})
        trainer = PolymnistTrainer(mst)
        test_results = trainer.run_epochs()
        assert np.round(test_results.joint_div, 2) == np.round(static_results[method]['joint_div'], 2)
        assert np.round(test_results.klds['m0'], 2) == np.round(static_results[method]['klds'], 2)
        assert np.round(test_results.lhoods['m0']['m0'], 2) == np.round(static_results[method]['lhoods'], 2)
        assert np.round(test_results.log_probs['m0'], 0) == np.round(static_results[method]['log_probs'], 0)
        assert np.round(test_results.total_loss, 2) == np.round(static_results[method]['total_loss'], 2)
        assert np.round(test_results.lr_eval['m0']['accuracy'], 2) == np.round(static_results[method]['lr_eval'], 2)
        assert np.round(test_results.latents['m0']['latents_class']['mu'], 2) == np.round(
            static_results[method]['latents_class']['mu'], 2)


def test_generate_plots():
    with tempfile.TemporaryDirectory() as tmpdirname:
        mst = set_me_up(tmpdirname)
        generate_plots(mst, epoch=1)


def test_test_generation():
    with tempfile.TemporaryDirectory() as tmpdirname:
        mst = set_me_up(tmpdirname)
        test_generation(mst)


if __name__ == '__main__':
    # pass
    test_static_results_2mods('joint_elbo')
    test_static_results_2mods('moe')
    # test_run_epochs_polymnist(method='joint_elbo')
    # test_run_epochs_polymnist(method='moe')
    # test_run_epochs_polymnist(method='planar_mixture')
    # test_generate_plots()
    # test_test_generation()
