import sys, os
import numpy as np
from itertools import cycle
import json
import random

import matplotlib.pyplot as plt
import torch
import torch.nn as nn
import torch.optim as optim
import torch.distributions as dist
from torch.autograd import Variable
from tensorboardX import SummaryWriter
from torch.utils.data import DataLoader

from mnistsvhntext.networks.VAEtrimodalSVHNMNIST import VAEtrimodalSVHNMNIST
from mnistsvhntext.networks.ConvNetworkImgClfMNIST import ClfImg as ClfImgMNIST
from mnistsvhntext.networks.ConvNetworkImgClfSVHN import ClfImgSVHN
from mnistsvhntext.networks.ConvNetworkTextClf import ClfText as ClfText

from utils.loss import log_prob_img, log_prob_text
from divergence_measures.kl_div import calc_kl_divergence
from divergence_measures.mm_div import poe

from mnistsvhntext.testing import generate_swapping_plot
from mnistsvhntext.testing import generate_conditional_fig_1a
from mnistsvhntext.testing import generate_conditional_fig_2a
from mnistsvhntext.testing import generate_random_samples_plots
from mnistsvhntext.testing import calculate_coherence
from mnistsvhntext.testing import classify_cond_gen_samples
from mnistsvhntext.testing import classify_latent_representations
from mnistsvhntext.testing import train_clf_lr
from utils.test_functions import calculate_inception_features_for_gen_evaluation
from utils.test_functions import calculate_fid, calculate_fid_dict
from utils.test_functions import calculate_prd, calculate_prd_dict
from utils.test_functions import get_clf_activations
from utils.test_functions import load_inception_activations
from mnistsvhntext.likelihood import calc_log_likelihood_batch


from mnistsvhntext.SVHNMNISTDataset import SVHNMNIST
from utils.transforms import get_transform_mnist
from utils.transforms import get_transform_svhn
from utils.save_samples import save_generated_samples_singlegroup
from utils import utils

torch.multiprocessing.set_sharing_strategy('file_system')

# global variables
SEED = None 
SAMPLE1 = None
if SEED is not None:
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    random.seed(SEED)


def get_10_mnist_samples(flags, svhnmnist, num_testing_images):
    samples = []
    for i in range(10):
        while True:
            m1, m2, m3, target = svhnmnist.__getitem__(random.randint(0, num_testing_images-1))
            if target == i:
                m1 = m1.to(flags.device)
                m2 = m2.to(flags.device)
                m3 = m3.to(flags.device);
                samples.append((m1, m2, m3, target))
                break;
    return samples


def run_epoch(epoch, vae_trimodal, optimizer, data, writer, alphabet, train=False, flags={},
              model_clf_svhn=None, model_clf_mnist=None, model_clf_m3 = None, clf_lr=None, step_logs=0):

    loader = cycle(DataLoader(data, batch_size=flags.batch_size, shuffle=True, num_workers=8, drop_last=True))

    # set up weights
    beta_style = flags.beta_style;
    beta_content = flags.beta_content;

    beta_m1_style = flags.beta_m1_style;
    beta_m2_style = flags.beta_m2_style;
    beta_m3_style = flags.beta_m3_style;

    rec_weight_m1 = vae_trimodal.rec_w1;
    rec_weight_m2 = vae_trimodal.rec_w2;
    rec_weight_m3 = vae_trimodal.rec_w3;

    if flags.kl_annealing > 0:
        step_size = flags.beta/flags.kl_annealing;
        if epoch < flags.kl_annealing:
            beta = 0.0001 + epoch*step_size;
        else:
            beta = flags.beta;
    else:
        beta = flags.beta;
    rec_weight = 1.0;

    if not train:
        vae_trimodal.eval();
        ll_mnist_mnist = []; ll_mnist_svhn = []; ll_mnist_m3 = []; ll_mnist_joint = [];
        ll_svhn_mnist = []; ll_svhn_svhn = []; ll_svhn_m3 = []; ll_svhn_joint = [];
        ll_m3_mnist = []; ll_m3_svhn = []; ll_m3_m3 = []; ll_m3_joint = [];
        ll_joint_mnist = []; ll_joint_svhn = []; ll_joint_m3 = []; ll_joint_joint = [];
        ll_ms_m3 = []; ll_ms_joint = []; ll_mt_svhn = []; ll_mt_joint = [];
        ll_st_mnist = []; ll_st_joint = [];
        lr_acc_m1_c = []; lr_acc_m2_c = []; lr_acc_m3_c = [];
        lr_acc_m1_s = []; lr_acc_m2_s = []; lr_acc_m3_s = [];
        lr_acc_m1m2 = []; lr_acc_m1m3 = []; lr_acc_m2m3 = [];
        lr_acc_joint = []; lr_acc_m1m2m3 = []; lr_acc_dyn_prior = [];
        cg_acc_m1 = {'m1': [], 'm2': [], 'm3': []};
        cg_acc_m2 = {'m1': [], 'm2': [], 'm3': []};
        cg_acc_m3 = {'m1': [], 'm2': [], 'm3': []};
        cg_acc_m1m2 = {'m1': [], 'm2': [], 'm3': []};
        cg_acc_m1m3 = {'m1': [], 'm2': [], 'm3': []};
        cg_acc_m2m3 = {'m1': [], 'm2': [], 'm3': []};
        cg_acc_dp_m1m2 = {'m1': [], 'm2': [], 'm3': []};
        cg_acc_dp_m1m3 = {'m1': [], 'm2': [], 'm3': []};
        cg_acc_dp_m2m3 = {'m1': [], 'm2': [], 'm3': []};
        random_gen_acc = [];
    else:
        vae_trimodal.train();

    mod_weights = utils.reweight_weights(torch.Tensor(flags.alpha_modalities));
    mod_weights = mod_weights.to(flags.device);

    num_batches_epoch = int(data.__len__() /float(flags.batch_size));

    step_print_progress = 0;
    for iteration in range(num_batches_epoch):
        # load a mini-batch
        batch = next(loader)
        m1_batch, m2_batch, m3_batch, labels_batch = batch;
        labels_batch = nn.functional.one_hot(labels_batch, num_classes=10).float()
        m1_batch = m1_batch.to(flags.device);
        m2_batch = m2_batch.to(flags.device);
        m3_batch = m3_batch.to(flags.device);
        labels_batch = labels_batch.to(flags.device);

        results_joint = vae_trimodal(input_mnist=Variable(m1_batch),
                                     input_svhn=Variable(m2_batch),
                                     input_m3=Variable(m3_batch));
        m1_reconstruction = results_joint['rec']['m1'];
        m2_reconstruction = results_joint['rec']['m2'];
        m3_reconstruction = results_joint['rec']['m3'];
        latents = results_joint['latents'];
        [m1_class_mu, m1_class_logvar] = latents['m1'];
        [m1_style_mu, m1_style_logvar] = latents['m1_style'];
        [m2_class_mu, m2_class_logvar] = latents['m2'];
        [m2_style_mu, m2_style_logvar] = latents['m2_style'];
        [m3_class_mu, m3_class_logvar] = latents['m3'];
        [m3_style_mu, m3_style_logvar] = latents['m3_style'];
        [m1m2_c_mu, m1m2_c_logvar] = latents['mnist_svhn'];
        [m1m3_c_mu, m1m3_c_logvar] = latents['mnist_m3'];
        [m2m3_c_mu, m2m3_c_logvar] = latents['svhn_m3'];
        [m1m2m3_c_mu, m1m2m3_c_logvar] = latents['mnist_svhn_m3'];
        [group_mu, group_logvar] = results_joint['group_distr'];
        group_divergence = results_joint['joint_divergence'];
        if flags.modality_jsd:
            [dyn_prior_mu, dyn_prior_logvar] = results_joint['dyn_prior'];
            kld_dyn_prior = calc_kl_divergence(dyn_prior_mu, dyn_prior_logvar, norm_value=flags.batch_size)

        if flags.factorized_representation:
            kld_m1_style = calc_kl_divergence(m1_style_mu, m1_style_logvar, norm_value=flags.batch_size)
            kld_m2_style = calc_kl_divergence(m2_style_mu, m2_style_logvar, norm_value=flags.batch_size)
            kld_m3_style = calc_kl_divergence(m3_style_mu, m3_style_logvar, norm_value=flags.batch_size)
        else:
            m1_style_mu = torch.zeros(1).to(flags.device);
            m1_style_logvar = torch.zeros(1).to(flags.device);
            m2_style_mu = torch.zeros(1).to(flags.device);
            m2_style_logvar = torch.zeros(1).to(flags.device);
            m3_style_mu = torch.zeros(1).to(flags.device);
            m3_style_logvar = torch.zeros(1).to(flags.device);
            kld_m1_style = torch.zeros(1).to(flags.device);
            kld_m2_style = torch.zeros(1).to(flags.device);
            kld_m3_style = torch.zeros(1).to(flags.device);

        kld_m1_class = calc_kl_divergence(m1_class_mu, m1_class_logvar, norm_value=flags.batch_size);
        kld_m2_class = calc_kl_divergence(m2_class_mu, m2_class_logvar, norm_value=flags.batch_size);
        kld_m3_class = calc_kl_divergence(m3_class_mu, m3_class_logvar, norm_value=flags.batch_size);
        kld_group = calc_kl_divergence(group_mu, group_logvar, norm_value=flags.batch_size);
        rec_error_m1 = -log_prob_img(m1_reconstruction, Variable(m1_batch), flags.batch_size);
        rec_error_m2 = -log_prob_img(m2_reconstruction, Variable(m2_batch), flags.batch_size);
        rec_error_m3 = -log_prob_m3(m3_reconstruction, Variable(m3_batch), flags.batch_size);

        rec_error_weighted = rec_weight_m1*rec_error_m1 + rec_weight_m2*rec_error_m2 + rec_weight_m3*rec_error_m3;
        if flags.modality_jsd or flags.modality_moe:
            kld_style = beta_m1_style * kld_m1_style + beta_m2_style * kld_m2_style + beta_m3_style*kld_m3_style;
            kld_content = group_divergence;
            kld_weighted_all = beta_style * kld_style + beta_content * kld_content;
            total_loss = rec_weight * rec_error_weighted + beta * kld_weighted_all
        elif flags.modality_poe:
            klds_joint = {'content': group_divergence,
                          'style': {'m1': kld_m1_style,
                                    'm2': kld_m2_style,
                                    'm3': kld_m3_style}}
            recs_joint = {'m1': rec_error_m1,
                          'm2': rec_error_m2,
                          'm3': rec_error_m3}
            elbo_joint = utils.calc_elbo(flags, 'joint', recs_joint, klds_joint);
            results_mnist = vae_trimodal(input_mnist=m1_batch,
                                         input_svhn=None,
                                         input_m3=None);
            mnist_m1_rec = results_mnist['rec']['m1'];
            mnist_m1_rec_error = -log_prob_img(mnist_m1_rec, m1_batch, flags.batch_size);
            recs_mnist = {'m1': mnist_m1_rec_error}
            klds_mnist = {'content': kld_m1_class,
                          'style': {'m1': kld_m1_style}};
            elbo_mnist = utils.calc_elbo(flags, 'm1', recs_mnist, klds_mnist);

            results_svhn = vae_trimodal(input_mnist=None,
                                         input_svhn=m2_batch,
                                         input_m3=None);
            svhn_m2_rec = results_svhn['rec']['m2']
            svhn_m2_rec_error = -log_prob_img(svhn_m2_rec, m2_batch, flags.batch_size);
            recs_svhn = {'m2': svhn_m2_rec_error};
            klds_svhn = {'content': kld_m2_class,
                         'style': {'m2': kld_m2_style}}
            elbo_svhn = utils.calc_elbo(flags, 'm2', recs_svhn, klds_svhn);

            results_m3 = vae_trimodal(input_mnist=None,
                                         input_svhn=None,
                                         input_m3=m3_batch);
            m3_m3_rec = results_m3['rec']['m3'];
            m3_m3_rec_error = -log_prob_m3(m3_m3_rec, m3_batch, flags.batch_size);
            recs_m3 = {'m3': m3_m3_rec_error};
            klds_m3 = {'content': kld_m3_class,
                         'style': {'m3': kld_m3_style}};
            elbo_m3 = utils.calc_elbo(flags, 'm3', recs_m3, klds_m3);
            total_loss = elbo_joint + elbo_mnist + elbo_svhn + elbo_m3;

        data_class_m1 = m1_class_mu.cpu().data.numpy();
        data_class_m2 = m2_class_mu.cpu().data.numpy();
        data_class_m3 = m3_class_mu.cpu().data.numpy();
        data_class_m1m2 = m1m2_c_mu.cpu().data.numpy();
        data_class_m1m3 = m1m3_c_mu.cpu().data.numpy();
        data_class_m2m3 = m2m3_c_mu.cpu().data.numpy();
        data_class_m1m2m3 = m1m2m3_c_mu.cpu().data.numpy();
        data_class_joint = group_mu.cpu().data.numpy();
        data = {'mnist': data_class_m1,
                'svhn': data_class_m2,
                'm3': data_class_m3,
                'ms': data_class_m1m2,
                'mt': data_class_m1m3,
                'st': data_class_m2m3,
                'mst': data_class_m1m2m3,
                'joint': data_class_joint,
                }
        if flags.factorized_representation:
            data_style_m1 = m1_style_mu.cpu().data.numpy();
            data_style_m2 = m2_style_mu.cpu().data.numpy();
            data_style_m3 = m3_style_mu.cpu().data.numpy();
            data['mnist_style'] = data_style_m1;
            data['svhn_style'] = data_style_m2;
            data['m3_style'] = data_style_m3;
        labels = labels_batch.cpu().data.numpy().reshape(flags.batch_size, 10);
        if (epoch + 1) % flags.eval_freq == 0 or (epoch + 1) == flags.end_epoch:
            if train == False:
                # log-likelihood
                if flags.calc_nll:
                    # 12 imp samples because dividible by 3 (needed for joint)
                    ll_mnist_batch = calc_log_likelihood_batch(flags, 'm1', batch, vae_trimodal, mod_weights, num_imp_samples=12)
                    ll_svhn_batch = calc_log_likelihood_batch(flags, 'm2', batch, vae_trimodal, mod_weights, num_imp_samples=12)
                    ll_m3_batch = calc_log_likelihood_batch(flags, 'm3', batch, vae_trimodal, mod_weights, num_imp_samples=12)
                    ll_ms_batch = calc_log_likelihood_batch(flags, 'mnist_svhn', batch, vae_trimodal, mod_weights, num_imp_samples=12);
                    ll_mt_batch = calc_log_likelihood_batch(flags, 'mnist_m3', batch, vae_trimodal, mod_weights, num_imp_samples=12);
                    ll_st_batch = calc_log_likelihood_batch(flags, 'svhn_m3', batch, vae_trimodal, mod_weights, num_imp_samples=12);
                    ll_joint = calc_log_likelihood_batch(flags, 'joint', batch, vae_trimodal, mod_weights, num_imp_samples=12);
                    ll_mnist_mnist.append(ll_mnist_batch['m1'].item())
                    ll_mnist_svhn.append(ll_mnist_batch['m2'].item())
                    ll_mnist_m3.append(ll_mnist_batch['m3'].item())
                    ll_mnist_joint.append(ll_mnist_batch['joint'].item())
                    ll_svhn_mnist.append(ll_svhn_batch['m1'].item())
                    ll_svhn_svhn.append(ll_svhn_batch['m2'].item())
                    ll_svhn_m3.append(ll_svhn_batch['m3'].item())
                    ll_svhn_joint.append(ll_svhn_batch['joint'].item())
                    ll_m3_mnist.append(ll_m3_batch['m1'].item())
                    ll_m3_svhn.append(ll_m3_batch['m2'].item())
                    ll_m3_m3.append(ll_m3_batch['m3'].item())
                    ll_m3_joint.append(ll_m3_batch['joint'].item())
                    ll_joint_mnist.append(ll_joint['m1'].item())
                    ll_joint_svhn.append(ll_joint['m2'].item())
                    ll_joint_m3.append(ll_joint['m3'].item())
                    ll_joint_joint.append(ll_joint['joint'].item());
                    ll_ms_m3.append(ll_ms_batch['m3'].item());
                    ll_ms_joint.append(ll_ms_batch['joint'].item());
                    ll_mt_svhn.append(ll_mt_batch['m2'].item());
                    ll_mt_joint.append(ll_mt_batch['joint'].item());
                    ll_st_mnist.append(ll_st_batch['m1'].item());
                    ll_st_joint.append(ll_st_batch['joint'].item());

                # conditional generation 1 modalitiy available
                latent_distr = dict();
                latent_distr['m1'] = [m1_class_mu, m1_class_logvar];
                latent_distr['m2'] = [m2_class_mu, m2_class_logvar];
                latent_distr['m3'] = [m3_class_mu, m3_class_logvar];
                if flags.modality_jsd:
                    latent_distr['dynamic_prior'] = [dyn_prior_mu, dyn_prior_logvar];
                    # latent_distr['dynamic_prioremp'] = [mu_emp_batch, logvar_emp_batch];
                rand_gen_samples = vae_trimodal.generate();
                cond_gen_samples = vae_trimodal.cond_generation_1a(latent_distr);
                m1_cond = cond_gen_samples['m1']  # samples conditioned on mnist;
                m2_cond = cond_gen_samples['m2']  # samples conditioned on svhn;
                m3_cond = cond_gen_samples['m3']  # samples conditioned on svhn;
                real_samples = {'m1': m1_batch, 'm2': m2_batch, 'm3': m3_batch}
                if (flags.batch_size*iteration) < flags.num_samples_fid:
                    save_generated_samples_singlegroup(flags, iteration, alphabet, 'real', real_samples)
                    save_generated_samples_singlegroup(flags, iteration, alphabet, 'random_sampling', rand_gen_samples)
                    save_generated_samples_singlegroup(flags, iteration, alphabet, 'cond_gen_1a2m_mnist', m1_cond)
                    save_generated_samples_singlegroup(flags, iteration, alphabet, 'cond_gen_1a2m_svhn', m2_cond)
                    save_generated_samples_singlegroup(flags, iteration,
                                                       alphabet,
                                                       'cond_gen_1a2m_m3', m3_cond)

                #conditional generation: 2 available modalities
                latent_distr_pairs = dict();
                latent_distr_pairs['m1_m2'] = {'latents': {'m1': [m1_class_mu, m1_class_logvar],
                                                                        'm2': [m2_class_mu, m2_class_logvar]},
                                                            'weights': [flags.alpha_modalities[1],
                                                                        flags.alpha_modalities[2]]};
                latent_distr_pairs['m1_m3'] = {'latents': {'m1': [m1_class_mu, m1_class_logvar],
                                                                    'm3': [m3_class_mu, m3_class_logvar]},
                                                        'weights': [flags.alpha_modalities[1],
                                                                    flags.alpha_modalities[3]]};
                latent_distr_pairs['m2_m3'] = {'latents': {'m2': [m2_class_mu, m2_class_logvar],
                                                                   'm3': [m3_class_mu, m3_class_logvar]},
                                                       'weights': [flags.alpha_modalities[2],
                                                                   flags.alpha_modalities[3]]};
                cond_gen_2a = vae_trimodal.cond_generation_2a(latent_distr_pairs)
                if (flags.batch_size*iteration) < flags.num_samples_fid:
                    save_generated_samples_singlegroup(flags, iteration, alphabet, 'cond_gen_2a1m_mnist_svhn',
                                                       cond_gen_2a['m1_m2']);
                    save_generated_samples_singlegroup(flags, iteration,
                                                       alphabet,
                                                       'cond_gen_2a1m_mnist_m3',
                                                       cond_gen_2a['m1_m3']);
                    save_generated_samples_singlegroup(flags, iteration,
                                                       alphabet,
                                                       'cond_gen_2a1m_svhn_m3',
                                                       cond_gen_2a['m2_m3']);

                if flags.modality_jsd:
                    # conditional generation 2 modalities available -> dyn
                    # prior generation
                    mus_ms = torch.cat([m1_class_mu.unsqueeze(0),
                                        m2_class_mu.unsqueeze(0)], dim=0);
                    logvars_ms = torch.cat([m1_class_logvar.unsqueeze(0),
                                            m2_class_logvar.unsqueeze(0)],
                                           dim=0);
                    poe_dp_ms = poe(mus_ms, logvars_ms);
                    
                    mus_mt = torch.cat([m1_class_mu.unsqueeze(0),
                                        m3_class_mu.unsqueeze(0)], dim=0);
                    logvars_mt = torch.cat([m1_class_logvar.unsqueeze(0),
                                            m3_class_logvar.unsqueeze(0)],
                                           dim=0);
                    poe_dp_mt = poe(mus_mt, logvars_mt);

                    mus_st = torch.cat([m2_class_mu.unsqueeze(0),
                                        m3_class_mu.unsqueeze(0)], dim=0);
                    logvars_st = torch.cat([m1_class_logvar.unsqueeze(0),
                                            m3_class_logvar.unsqueeze(0)],
                                           dim=0);
                    poe_dp_st = poe(mus_st, logvars_st);
                    l_poe_dp = {'m1_m2': poe_dp_ms,
                                'm1_m3': poe_dp_mt,
                                'm2_m3': poe_dp_st}
                    cond_gen_dp = vae_trimodal.cond_generation_1a(l_poe_dp);
                    if (flags.batch_size*iteration) < flags.num_samples_fid:
                        save_generated_samples_singlegroup(flags, iteration,
                                                           alphabet,
                                                           'dynamic_prior_mnist_svhn',
                                                           cond_gen_dp['m1_m2']);
                        save_generated_samples_singlegroup(flags, iteration, alphabet,
                                                           'dynamic_prior_mnist_m3',
                                                           cond_gen_dp['m1_m3']);
                        save_generated_samples_singlegroup(flags, iteration,
                                                           alphabet,
                                                           'dynamic_prior_2a1m_svhn_m3',
                                                           cond_gen_dp['m2_m3']);

                if model_clf_mnist is not None and model_clf_svhn is not None
                and model_clf_m3 is not None:
                    clfs_gen = {'m1': model_clf_mnist,
                                'm2': model_clf_svhn,
                                'm3': model_clf_m3};
                    coherence_random_triples = calculate_coherence(clfs_gen, rand_gen_samples);
                    random_gen_acc.append(coherence_random_triples)

                    cond_m1_acc = classify_cond_gen_samples(flags, epoch,
                                                            clfs_gen, labels,
                                                            m1_cond)[-1];
                    cg_acc_m1['m1'].append(cond_m1_acc['m1']);
                    cg_acc_m1['m2'].append(cond_m1_acc['m2']);
                    cg_acc_m1['m3'].append(cond_m1_acc['m3']);
                    cond_m2_acc = classify_cond_gen_samples(flags, epoch,
                                                            clfs_gen, labels,
                                                            m2_cond)[-1];
                    cg_acc_m2['m1'].append(cond_m2_acc['m1']);
                    cg_acc_m2['m2'].append(cond_m2_acc['m2']);
                    cg_acc_m2['m3'].append(cond_m2_acc['m3']);
                    cond_m3_acc = classify_cond_gen_samples(flags, epoch,
                                                            clfs_gen, labels,
                                                            m3_cond)[-1];
                    cg_acc_m3['m1'].append(cond_m3_acc['m1']);
                    cg_acc_m3['m2'].append(cond_m3_acc['m2']);
                    cg_acc_m3['m3'].append(cond_m3_acc['m3']);

                    cond_ms_acc = classify_cond_gen_samples(flags, epoch, clfs_gen, labels,
                                                            cond_gen_2a['m1_m2'])[-1];
                    cg_acc_m1m2['m1'].append(cond_ms_acc['m1']);
                    cg_acc_m1m2['m2'].append(cond_ms_acc['m2']);
                    cg_acc_m1m2['m3'].append(cond_ms_acc['m3']);
                    cond_mt_acc = classify_cond_gen_samples(flags, epoch, clfs_gen, labels,
                                                            cond_gen_2a['m1_m3'])[-1];
                    cg_acc_m1m3['m1'].append(cond_mt_acc['m1']);
                    cg_acc_m1m3['m2'].append(cond_mt_acc['m2']);
                    cg_acc_m1m3['m3'].append(cond_mt_acc['m3']);
                    cond_st_acc = classify_cond_gen_samples(flags, epoch, clfs_gen, labels,
                                                            cond_gen_2a['m2_m3'])[-1];
                    cg_acc_m2m3['m1'].append(cond_st_acc['m1']);
                    cg_acc_m2m3['m2'].append(cond_st_acc['m2']);
                    cg_acc_m2m3['m3'].append(cond_st_acc['m3']);

                    if flags.modality_jsd:
                        cond_dp_ms_acc = classify_cond_gen_samples(flags,
                                                                   epoch,
                                                                   clfs_gen,
                                                                   labels,
                                                                   cond_gen_dp['m1_m2'])[-1];
                        cg_acc_dp_m1m2['m1'].append(cond_dp_ms_acc['m1']);
                        cg_acc_dp_m1m2['m2'].append(cond_dp_ms_acc['m2']);
                        cg_acc_dp_m1m2['m3'].append(cond_dp_ms_acc['m3']);
                        cond_dp_mt_acc = classify_cond_gen_samples(flags,
                                                               epoch,
                                                               clfs_gen,
                                                               labels,
                                                               cond_gen_dp['m1_m3'])[-1];
                        cg_acc_dp_m1m3['m1'].append(cond_dp_mt_acc['m1']);
                        cg_acc_dp_m1m3['m2'].append(cond_dp_mt_acc['m2']);
                        cg_acc_dp_m1m3['m3'].append(cond_dp_mt_acc['m3']);
                        cond_dp_st_acc = classify_cond_gen_samples(flags,
                                                                   epoch,
                                                                   clfs_gen,
                                                                   labels,
                                                                   cond_gen_dp['m2_m3'])[-1];
                        cg_acc_dp_m2m3['m1'].append(cond_dp_st_acc['m1']);
                        cg_acc_dp_m2m3['m2'].append(cond_dp_st_acc['m2']);
                        cg_acc_dp_m2m3['m3'].append(cond_dp_st_acc['m3']);

            if train:
                if iteration == (num_batches_epoch - 1):
                    clf_lr = train_clf_lr(flags, data, labels);
            else:
                if clf_lr is not None:
                    accuracies = classify_latent_representations(flags, epoch, clf_lr, data, labels);
                    lr_acc_m1_c.append(np.mean(accuracies['mnist']))
                    lr_acc_m2_c.append(np.mean(accuracies['svhn']))
                    lr_acc_m3_c.append(np.mean(accuracies['m3']))
                    lr_acc_m1m2.append(np.mean(accuracies['ms']))
                    lr_acc_m1m3.append(np.mean(accuracies['mt']))
                    lr_acc_m2m3.append(np.mean(accuracies['st']))
                    lr_acc_m1m2m3.append(np.mean(accuracies['mst']))
                    lr_acc_joint.append(np.mean(accuracies['joint']))
                    if flags.modality_jsd:
                        lr_acc_dyn_prior.append(np.mean(accuracies['dyn_prior']));
                    if flags.factorized_representation:
                        lr_acc_m1_s.append(np.mean(accuracies['mnist_style']))
                        lr_acc_m2_s.append(np.mean(accuracies['svhn_style']))
                        lr_acc_m3_s.append(np.mean(accuracies['m3_style']))

        # backprop
        if train == True:
            optimizer.zero_grad()
            total_loss.backward()
            optimizer.step()
            # utils.printProgressBar(step_print_progress, num_batches_epoch)

        # write scalars to tensorboard
        name = "train" if train else "test"
        writer.add_scalars('%s/Loss' % name, {'loss': total_loss.data.item()}, step_logs)
        writer.add_scalars('%s/RecLoss' % name, {
            'M1': rec_error_m1.item(),
            'M2': rec_error_m2.item(),
            'M3': rec_error_m3.item(),
        }, step_logs)
        writer.add_scalars('%s/KLD' % name, {
            'Content_M1': kld_m1_class.item(),
            'Style_M1': kld_m1_style.item(),
            'Content_M2': kld_m2_class.item(),
            'Style_M2': kld_m2_style.item(),
            'Content_M3': kld_m3_class.item(),
            'Style_M3': kld_m3_style.item(),
            }, step_logs)
        writer.add_scalars('%s/group_divergence' % name, {
            'group_div': group_divergence.item(),
            'KLDgroup': kld_group.item(),
        }, step_logs)
        if flags.modality_jsd:
            writer.add_scalars('%s/group_divergence' % name, {
                'KLDdyn_prior': kld_dyn_prior.item(),
            }, step_logs)
            writer.add_scalars('%s/mu' % name, {
                'content_alpha': group_mu.mean().item(),
            }, step_logs)
            writer.add_scalars('%s/logvar' % name, {
                'content_alpha': group_logvar.mean().item(),
            }, step_logs)
        writer.add_scalars('%s/mu' % name, {
            'content_m1': m1_class_mu.mean().item(),
            'style_m1': m1_style_mu.mean().item(),
            'content_m2': m2_class_mu.mean().item(),
            'style_m2': m2_style_mu.mean().item(),
            'content_m3': m3_class_mu.mean().item(),
            'style_m3': m3_style_mu.mean().item(),
        }, step_logs)
        writer.add_scalars('%s/logvar' % name, {
            'style_m1': m1_style_logvar.mean().item(),
            'content_m1': m1_class_logvar.mean().item(),
            'style_m2': m2_style_logvar.mean().item(),
            'content_m2': m2_class_logvar.mean().item(),
            'style_m3': m3_style_logvar.mean().item(),
            'content_m3': m3_class_logvar.mean().item(),
        }, step_logs)
        step_logs += 1
        step_print_progress += 1;

    # write style-transfer ("swapping") figure to tensorboard
    if train == False:
        if flags.factorized_representation:
            # mnist to mnist: swapping content and style intra modal
            swapping_figs = generate_swapping_plot(flags, epoch, vae_trimodal,
                                                   SAMPLE1, alphabet)
            swaps_mnist_content = swapping_figs['m1'];
            swaps_svhn_content = swapping_figs['m2'];
            swaps_m3_content = swapping_figs['m3'];
            swap_mnist_mnist = swaps_mnist_content['m1'];
            swap_mnist_svhn = swaps_mnist_content['m2'];
            swap_mnist_m3 = swaps_mnist_content['m3'];
            swap_svhn_mnist = swaps_svhn_content['m1'];
            swap_svhn_svhn = swaps_svhn_content['m2'];
            swap_svhn_m3 = swaps_svhn_content['m3'];
            swap_m3_mnist = swaps_m3_content['m1'];
            swap_m3_svhn = swaps_m3_content['m2'];
            swap_m3_m3 = swaps_m3_content['m3'];
            writer.add_image('Swapping mnist to mnist', swap_mnist_mnist, epoch, dataformats="HWC")
            writer.add_image('Swapping mnist to svhn', swap_mnist_svhn, epoch, dataformats="HWC")
            writer.add_image('Swapping mnist to m3', swap_mnist_m3, epoch, dataformats="HWC")
            writer.add_image('Swapping svhn to mnist', swap_svhn_mnist, epoch, dataformats="HWC")
            writer.add_image('Swapping svhn to svhn', swap_svhn_svhn, epoch, dataformats="HWC")
            writer.add_image('Swapping svhn to m3', swap_svhn_m3, epoch, dataformats="HWC")
            writer.add_image('Swapping m3 to mnist', swap_m3_mnist, epoch, dataformats="HWC")
            writer.add_image('Swapping m3 to svhn', swap_m3_svhn, epoch, dataformats="HWC")
            writer.add_image('Swapping m3 to m3', swap_m3_m3, epoch, dataformats="HWC")

        conditional_figs = generate_conditional_fig_1a(flags, epoch, vae_trimodal, SAMPLE1, alphabet)
        figs_cond_mnist = conditional_figs['m1'];
        figs_cond_svhn = conditional_figs['m2'];
        figs_cond_m3 = conditional_figs['m3'];
        cond_mnist_mnist = figs_cond_mnist['m1'];
        cond_mnist_svhn = figs_cond_mnist['m2'];
        cond_mnist_m3 = figs_cond_mnist['m3'];
        cond_svhn_mnist = figs_cond_svhn['m1'];
        cond_svhn_svhn = figs_cond_svhn['m2'];
        cond_svhn_m3 = figs_cond_svhn['m3'];
        cond_m3_mnist = figs_cond_m3['m1'];
        cond_m3_svhn = figs_cond_m3['m2'];
        cond_m3_m3 = figs_cond_m3['m3'];
        writer.add_image('Cond_mnist_to_mnist', cond_mnist_mnist, epoch, dataformats="HWC")
        writer.add_image('Cond_mnist_to_svhn', cond_mnist_svhn, epoch, dataformats="HWC")
        writer.add_image('Cond_mnist_to_m3', cond_mnist_m3, epoch, dataformats="HWC")
        writer.add_image('Cond_svhn_to_mnist', cond_svhn_mnist, epoch, dataformats="HWC")
        writer.add_image('Cond_svhn_to_svhn', cond_svhn_svhn, epoch, dataformats="HWC")
        writer.add_image('Cond_svhn_to_m3', cond_svhn_m3, epoch, dataformats="HWC")
        writer.add_image('Cond_m3_to_mnist', cond_m3_mnist, epoch, dataformats="HWC")
        writer.add_image('Cond_m3_to_svhn', cond_m3_svhn, epoch, dataformats="HWC")
        writer.add_image('Cond_m3_to_m3', cond_m3_m3, epoch, dataformats="HWC")

        conditional_figs_2a = generate_conditional_fig_2a(flags, epoch,
                                                          vae_trimodal,
                                                          SAMPLE1, alphabet);
        figs_cond_ms = conditional_figs_2a['mnist_svhn'];
        figs_cond_mt = conditional_figs_2a['mnist_m3'];
        figs_cond_st = conditional_figs_2a['svhn_m3'];
        cond_ms_m = figs_cond_ms['m1'];
        cond_ms_s = figs_cond_ms['m2'];
        cond_ms_t = figs_cond_ms['m3'];
        cond_mt_m = figs_cond_mt['m1'];
        cond_mt_s = figs_cond_mt['m2'];
        cond_mt_t = figs_cond_mt['m3'];
        cond_st_m = figs_cond_st['m1'];
        cond_st_s = figs_cond_st['m2'];
        cond_st_t = figs_cond_st['m3'];
        writer.add_image('Cond_ms_to_m', cond_ms_m, epoch, dataformats="HWC")
        writer.add_image('Cond_ms_to_s', cond_ms_s, epoch, dataformats="HWC")
        writer.add_image('Cond_ms_to_t', cond_ms_t, epoch, dataformats="HWC")
        writer.add_image('Cond_mt_to_m', cond_mt_m, epoch, dataformats="HWC")
        writer.add_image('Cond_mt_to_s', cond_mt_s, epoch, dataformats="HWC")
        writer.add_image('Cond_mt_to_t', cond_mt_t, epoch, dataformats="HWC")
        writer.add_image('Cond_st_to_m', cond_st_m, epoch, dataformats="HWC")
        writer.add_image('Cond_st_to_s', cond_st_s, epoch, dataformats="HWC")
        writer.add_image('Cond_st_to_t', cond_st_t, epoch, dataformats="HWC")

        random_figs = generate_random_samples_plots(flags, epoch,
                                                    vae_trimodal, alphabet);
        random_mnist = random_figs['m1'];
        random_svhn = random_figs['m2'];
        random_m3 = random_figs['m3'];
        writer.add_image('Random MNIST', random_mnist, epoch, dataformats="HWC");
        writer.add_image('Random SVHN', random_svhn, epoch, dataformats="HWC");
        writer.add_image('Random Text', random_m3, epoch, dataformats="HWC");

        if train == False:
            if (epoch + 1) % flags.eval_freq == 0 or (epoch + 1) == flags.end_epoch:
                cg_acc_m1['m1'] = np.mean(np.array(cg_acc_m1['m1']))
                cg_acc_m1['m2'] = np.mean(np.array(cg_acc_m1['m2']))
                cg_acc_m1['m3'] = np.mean(np.array(cg_acc_m1['m3']))
                cg_acc_m2['m1'] = np.mean(np.array(cg_acc_m2['m1']))
                cg_acc_m2['m2'] = np.mean(np.array(cg_acc_m2['m2']))
                cg_acc_m2['m3'] = np.mean(np.array(cg_acc_m2['m3']))
                cg_acc_m3['m1'] = np.mean(np.array(cg_acc_m3['m1']))
                cg_acc_m3['m2'] = np.mean(np.array(cg_acc_m3['m2']))
                cg_acc_m3['m3'] = np.mean(np.array(cg_acc_m3['m3']))
                writer.add_scalars('%s/cond_mnist_clf_accuracy' % name,
                                   cg_acc_m1, step_logs)
                writer.add_scalars('%s/cond_svhn_clf_accuracy' % name,
                                   cg_acc_m2, step_logs)
                writer.add_scalars('%s/cond_m3_clf_accuracy' % name,
                                   cg_acc_m3, step_logs)
                writer.add_scalars('%s/coherence' % name, {
                    'random': np.mean(np.array(random_gen_acc)),
                }, step_logs)
                cg_acc_m1m2['m1'] = np.mean(np.array(cg_acc_m1m2['m1']))
                cg_acc_m1m2['m2'] = np.mean(np.array(cg_acc_m1m2['m2']))
                cg_acc_m1m2['m3'] = np.mean(np.array(cg_acc_m1m2['m3']))
                cg_acc_m1m3['m1'] = np.mean(np.array(cg_acc_m1m3['m1']))
                cg_acc_m1m3['m2'] = np.mean(np.array(cg_acc_m1m3['m2']))
                cg_acc_m1m3['m3'] = np.mean(np.array(cg_acc_m1m3['m3']))
                cg_acc_m2m3['m1'] = np.mean(np.array(cg_acc_m2m3['m1']))
                cg_acc_m2m3['m2'] = np.mean(np.array(cg_acc_m2m3['m2']))
                cg_acc_m2m3['m3'] = np.mean(np.array(cg_acc_m2m3['m3']))
                writer.add_scalars('%s/cond_ms_clf_accuracy' % name,
                                   cg_acc_m1m2, step_logs)
                writer.add_scalars('%s/cond_mt_clf_accuracy' % name,
                                   cg_acc_m1m3, step_logs)
                writer.add_scalars('%s/cond_st_clf_accuracy' % name,
                                   cg_acc_m2m3, step_logs)
                if flags.modality_jsd:
                    cg_acc_dp_m1m2['m1'] = np.mean(np.array(cg_acc_dp_m1m2['m1']))
                    cg_acc_dp_m1m2['m2'] = np.mean(np.array(cg_acc_dp_m1m2['m2']))
                    cg_acc_dp_m1m2['m3'] = np.mean(np.array(cg_acc_dp_m1m2['m3']))
                    cg_acc_dp_m1m3['m1'] = np.mean(np.array(cg_acc_dp_m1m3['m1']))
                    cg_acc_dp_m1m3['m2'] = np.mean(np.array(cg_acc_dp_m1m3['m2']))
                    cg_acc_dp_m1m3['m3'] = np.mean(np.array(cg_acc_dp_m1m3['m3']))
                    cg_acc_dp_m2m3['m1'] = np.mean(np.array(cg_acc_dp_m2m3['m1']))
                    cg_acc_dp_m2m3['m2'] = np.mean(np.array(cg_acc_dp_m2m3['m2']))
                    cg_acc_dp_m2m3['m3'] = np.mean(np.array(cg_acc_dp_m2m3['m3']))
                    writer.add_scalars('%s/cond_st_dp_clf_accuracy' % name,
                                       cg_acc_dp_m1m2, step_logs)
                    writer.add_scalars('%s/cond_mt_dp_clf_accuracy' % name,
                                       cg_acc_dp_m1m3, step_logs)
                    writer.add_scalars('%s/cond_ms_dp_clf_accuracy' % name,
                                       cg_acc_dp_m2m3, step_logs)
                writer.add_scalars('%s/representation_accuracy' % name, {
                    'acc_m1': np.mean(np.array(lr_acc_m1_c)),
                    'acc_m2': np.mean(np.array(lr_acc_m2_c)),
                    'acc_m3': np.mean(np.array(lr_acc_m3_c)),
                    'acc_m1m2': np.mean(np.array(lr_acc_m1m2)),
                    'acc_m1m3': np.mean(np.array(lr_acc_m1m3)),
                    'acc_m2m3': np.mean(np.array(lr_acc_m2m3)),
                    'acc_m1m2m3': np.mean(np.array(lr_acc_m1m2m3)),
                    'acc_joint': np.mean(np.array(lr_acc_joint)),
                }, step_logs)
                if flags.modality_jsd:
                    writer.add_scalars('%s/representation_accuracy' % name, {
                        'acc_dyn_prior': np.mean(np.array(lr_acc_dyn_prior)),
                    }, step_logs)
                if flags.factorized_representation:
                    writer.add_scalars('%s/representation_accuracy' % name, {
                        'acc_style_m1': np.mean(np.array(lr_acc_m1_s)),
                        'acc_style_m2': np.mean(np.array(lr_acc_m2_s)),
                        'acc_style_m3': np.mean(np.array(lr_acc_m3_s)),
                    }, step_logs)
                if flags.calc_nll:
                    writer.add_scalars('%s/marginal_loglikelihood' % name, {
                        'mnist_mnist': np.mean(ll_mnist_mnist),
                        'mnist_svhn': np.mean(ll_mnist_svhn),
                        'mnist_m3': np.mean(ll_mnist_m3),
                        'mnist_joint': np.mean(ll_mnist_joint),
                        'svhn_mnist': np.mean(ll_svhn_mnist),
                        'svhn_svhn': np.mean(ll_svhn_svhn),
                        'svhn_m3': np.mean(ll_svhn_m3),
                        'svhn_joint': np.mean(ll_svhn_joint),
                        'm3_mnist': np.mean(ll_m3_mnist),
                        'm3_svhn': np.mean(ll_m3_svhn),
                        'm3_m3': np.mean(ll_m3_svhn),
                        'm3_joint': np.mean(ll_m3_joint),
                        'synergy_mnist': np.mean(ll_joint_mnist),
                        'synergy_svhn': np.mean(ll_joint_svhn),
                        'synergy_m3': np.mean(ll_joint_m3),
                        'joint': np.mean(ll_joint_joint),
                        'ms_m3': np.mean(ll_ms_m3),
                        'ms_joint': np.mean(ll_ms_joint),
                        'mt_svhn': np.mean(ll_mt_svhn),
                        'mt_joint': np.mean(ll_mt_joint),
                        'st_mnist': np.mean(ll_st_mnist),
                        'st_joint': np.mean(ll_st_joint),
                    }, step_logs)
        if ((epoch + 1) % flags.eval_freq_fid == 0 or (epoch + 1) == flags.end_epoch):
            cond_1a2m = {'m1': os.path.join(flags.dir_gen_eval_fid_cond_gen_1a2m, 'mnist'),
                         'm2': os.path.join(flags.dir_gen_eval_fid_cond_gen_1a2m, 'svhn'),
                         'm3':
                         os.path.join(flags.dir_gen_eval_fid_cond_gen_1a2m, 'm3')}
            cond_2a1m = {'m1_m2': os.path.join(flags.dir_gen_eval_fid_cond_gen_2a1m, 'mnist_svhn'),
                         'm1_m3':
                         os.path.join(flags.dir_gen_eval_fid_cond_gen_2a1m,
                                      'mnist_m3'),
                         'm2_m3':
                         os.path.join(flags.dir_gen_eval_fid_cond_gen_2a1m,
                                      'svhn_m3')}
            dyn_prior_2a = {'m1_m2': os.path.join(flags.dir_gen_eval_fid_dynamicprior, 'mnist_svhn'),
                            'm1_m3':
                            os.path.join(flags.dir_gen_eval_fid_dynamicprior,
                                         'mnist_m3'),
                            'm2_m3':
                            os.path.join(flags.dir_gen_eval_fid_dynamicprior,
                                         'svhn_m3')}
            if (epoch+1) == flags.eval_freq_fid:
                paths = {'real': flags.dir_gen_eval_fid_real,
                         'conditional_1a2m': cond_1a2m,
                         'conditional_2a1m': cond_2a1m,
                         'random': flags.dir_gen_eval_fid_random}
            else:
                paths = {'conditional_1a2m': cond_1a2m,
                         'conditional_2a1m': cond_2a1m,
                         'random': flags.dir_gen_eval_fid_random}
            if flags.modality_jsd:
                paths['dynamic_prior'] = dyn_prior_2a;
            calculate_inception_features_for_gen_evaluation(flags, paths,
                                                            modality='m1');
            calculate_inception_features_for_gen_evaluation(flags, paths,
                                                            modality='m2');
            if flags.modality_poe or flags.modality_moe:
                conds = [cond_1a2m, cond_2a1m];
            else:
                conds = [cond_1a2m, cond_2a1m, dyn_prior_2a];
            act_svhn = load_inception_activations(flags, 'm2', num_modalities=3, conditionals=conds);
            [act_inc_real_svhn, act_inc_rand_svhn, cond_1a2m_svhn, cond_2a1m_svhn, act_inc_dynprior_svhn] = act_svhn;
            act_mnist = load_inception_activations(flags, 'm1', num_modalities=3, conditionals=conds)
            [act_inc_real_mnist, act_inc_rand_mnist, cond_1a2m_mnist, cond_2a1m_mnist, act_inc_dynprior_mnist] = act_mnist;
            fid_random_svhn = calculate_fid(act_inc_real_svhn, act_inc_rand_svhn);
            fid_cond_2a1m_svhn = calculate_fid_dict(act_inc_real_svhn, cond_2a1m_svhn);
            fid_cond_1a2m_svhn = calculate_fid_dict(act_inc_real_svhn, cond_1a2m_svhn);
            fid_random_mnist = calculate_fid(act_inc_real_mnist, act_inc_rand_mnist);
            fid_cond_2a1m_mnist = calculate_fid_dict(act_inc_real_mnist, cond_2a1m_mnist);
            fid_cond_1a2m_mnist = calculate_fid_dict(act_inc_real_mnist, cond_1a2m_mnist);
            ap_prd_random_svhn = calculate_prd(act_inc_real_svhn, act_inc_rand_svhn);
            ap_prd_cond_2a1m_svhn = calculate_prd_dict(act_inc_real_svhn, cond_2a1m_svhn);
            ap_prd_cond_1a2m_svhn = calculate_prd_dict(act_inc_real_svhn, cond_1a2m_svhn);
            ap_prd_random_mnist = calculate_prd(act_inc_real_mnist, act_inc_rand_mnist);
            ap_prd_cond_1a2m_mnist = calculate_prd_dict(act_inc_real_mnist, cond_1a2m_mnist);
            ap_prd_cond_2a1m_mnist = calculate_prd_dict(act_inc_real_mnist, cond_2a1m_mnist);
            if flags.modality_jsd:
                fid_dp_2a1m_mnist = calculate_fid_dict(act_inc_real_mnist, act_inc_dynprior_mnist);
                ap_prd_dp_2a1m_mnist = calculate_prd_dict(act_inc_real_mnist, act_inc_dynprior_mnist);
                fid_dp_2a1m_svhn = calculate_fid_dict(act_inc_real_svhn, act_inc_dynprior_svhn);
                ap_prd_dp_2a1m_svhn = calculate_prd_dict(act_inc_real_svhn, act_inc_dynprior_svhn);

            writer.add_scalars('%s/fid' % name, {
                'mnist_random': fid_random_mnist,
                'svhn_random': fid_random_svhn,
                'svhn_cond_1a2m_svhn': fid_cond_1a2m_svhn['m2'],
                'svhn_cond_1a2m_mnist': fid_cond_1a2m_svhn['m1'],
                'svhn_cond_1a2m_m3': fid_cond_1a2m_svhn['m3'],
                'mnist_cond_1a2m_svhn': fid_cond_1a2m_mnist['m2'],
                'mnist_cond_1a2m_mnist': fid_cond_1a2m_mnist['m1'],
                'mnist_cond_1a2m_m3': fid_cond_1a2m_mnist['m3'],
                'svhn_2a1m_mnist_m3': fid_cond_2a1m_svhn['m1_m3'],
                'mnist_2a1m_svhn_m3': fid_cond_2a1m_mnist['m2_m3'],
            }, step_logs)
            writer.add_scalars('%s/prd' % name, {
                'mnist_random': ap_prd_random_mnist,
                'svhn_random': ap_prd_random_svhn,
                'svhn_cond_1a2m_svhn': ap_prd_cond_1a2m_svhn['m2'],
                'svhn_cond_1a2m_mnist': ap_prd_cond_1a2m_svhn['m1'],
                'svhn_cond_1a2m_m3': ap_prd_cond_1a2m_svhn['m3'],
                'mnist_cond_1a2m_svhn': ap_prd_cond_1a2m_mnist['m2'],
                'mnist_cond_1a2m_mnist': ap_prd_cond_1a2m_mnist['m1'],
                'mnist_cond_1a2m_m3': ap_prd_cond_1a2m_mnist['m3'],
                'svhn_2a1m_mnist_m3': ap_prd_cond_2a1m_svhn['m1_m3'],
                'mnist_2a1m_svhn_m3': ap_prd_cond_2a1m_mnist['m2_m3'],
            }, step_logs)
            if flags.modality_jsd:
                writer.add_scalars('%s/fid' % name, {
                    'mnist_dp_2a1m_st': fid_dp_2a1m_mnist['m2_m3'],
                    'svhn_dp_2a1m_mt': fid_dp_2a1m_svhn['m1_m3'],
                }, step_logs)
                writer.add_scalars('%s/prd' % name, {
                    'mnist_dp_2a1m_st': ap_prd_dp_2a1m_mnist['m2_m3'],
                    'svhn_dp_2a1m_mt': ap_prd_dp_2a1m_svhn['m1_m3'],
                }, step_logs)
    return step_logs, clf_lr;


def training_svhnmnist(FLAGS):
    global SAMPLE1, SAMPLE2, SEED

    # load data set and create data loader instance
    print('Loading MNIST (multimodal) dataset...')
    alphabet_path = os.path.join(os.getcwd(), 'alphabet.json');
    with open(alphabet_path) as alphabet_file:
        alphabet = str(''.join(json.load(alphabet_file)))
    FLAGS.num_features = len(alphabet)

    transform_mnist = get_transform_mnist(FLAGS);
    transform_svhn = get_transform_svhn(FLAGS);
    transforms = [transform_mnist, transform_svhn];
    svhnmnist_train = SVHNMNIST(FLAGS.dir_data, FLAGS.len_sequence,  alphabet, train=True, transform=transforms,
                                data_multiplications=FLAGS.data_multiplications)
    svhnmnist_test = SVHNMNIST(FLAGS.dir_data, FLAGS.len_sequence,  alphabet, train=False, transform=transforms,
                               data_multiplications=FLAGS.data_multiplications)

    use_cuda = torch.cuda.is_available();
    FLAGS.device = torch.device('cuda' if use_cuda else 'cpu');
    # load global samples
    SAMPLE1 = get_10_mnist_samples(FLAGS, svhnmnist_test, num_testing_images=svhnmnist_test.__len__())

    # model definition
    vae_trimodal = VAEtrimodalSVHNMNIST(FLAGS);

    # load saved models if load_saved flag is true
    if FLAGS.load_saved:
        vae_trimodal.load_state_dict(torch.load(os.path.join(FLAGS.dir_checkpoints, FLAGS.vae_trimodal_save)));

    model_clf_svhn = None;
    model_clf_mnist = None;
    model_clf_m3 = None;
    if FLAGS.use_clf:
        model_clf_mnist = ClfImgMNIST();
        model_clf_mnist.load_state_dict(torch.load(os.path.join(FLAGS.dir_clf, FLAGS.clf_save_m1)))
        model_clf_svhn = ClfImgSVHN();
        model_clf_svhn.load_state_dict(torch.load(os.path.join(FLAGS.dir_clf, FLAGS.clf_save_m2)))
        model_clf_m3 = ClfText(FLAGS);
        model_clf_m3.load_state_dict(torch.load(os.path.join(FLAGS.dir_clf, FLAGS.clf_save_m3)))

    vae_trimodal = vae_trimodal.to(FLAGS.device);
    if model_clf_m3 is not None:
        model_clf_m3 = model_clf_m3.to(FLAGS.device);
    if model_clf_mnist is not None:
        model_clf_mnist = model_clf_mnist.to(FLAGS.device);
    if model_clf_svhn is not None:
        model_clf_svhn = model_clf_svhn.to(FLAGS.device);

    # optimizer definition
    auto_encoder_optimizer = optim.Adam(
        list(vae_trimodal.parameters()),
        lr=FLAGS.initial_learning_rate,
        betas=(FLAGS.beta_1, FLAGS.beta_2))

    # initialize summary writer
    writer = SummaryWriter(FLAGS.dir_logs)

    str_flags = utils.save_and_log_flags(FLAGS);
    writer.add_m3('FLAGS', str_flags, 0)

    print('training epochs progress:')
    it_num_batches = 0;
    for epoch in range(FLAGS.start_epoch, FLAGS.end_epoch):
        utils.printProgressBar(epoch, FLAGS.end_epoch)
        # one epoch of training and testing
        it_num_batches, clf_lr = run_epoch(epoch, vae_trimodal, auto_encoder_optimizer, svhnmnist_train, writer, alphabet,
                                           train=True, flags=FLAGS,
                                           model_clf_svhn=model_clf_svhn,
                                           model_clf_mnist=model_clf_mnist,
                                           model_clf_m3=model_clf_m3,
                                           clf_lr=None,
                                           step_logs=it_num_batches)

        with torch.no_grad():
            it_num_batches, clf_lr = run_epoch(epoch, vae_trimodal, auto_encoder_optimizer, svhnmnist_test, writer, alphabet,
                                               train=False, flags=FLAGS,
                                               model_clf_svhn=model_clf_svhn,
                                               model_clf_mnist=model_clf_mnist,
                                               model_clf_m3=model_clf_m3,
                                               clf_lr=clf_lr,
                                               step_logs=it_num_batches)

        # save checkpoints after every 5 epochs
        if (epoch + 1) % 5 == 0 or (epoch + 1) == FLAGS.end_epoch:
            dir_network_epoch = os.path.join(FLAGS.dir_checkpoints, str(epoch).zfill(4));
            if not os.path.exists(dir_network_epoch):
                os.makedirs(dir_network_epoch);
            vae_trimodal.save_networks()
            torch.save(vae_trimodal.state_dict(), os.path.join(dir_network_epoch, FLAGS.vae_trimodal_save))
