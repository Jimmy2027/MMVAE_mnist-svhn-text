from typing import Mapping

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from torch.utils.data import DataLoader
from tqdm import tqdm

from mmvae_hub import log
from mmvae_hub.base.utils.utils import atleast_2d
from mmvae_hub.base.utils.utils import dict_to_device


def train_clf_lr_all_subsets(exp):
    """
    Encodes samples from the training set and train line classifiers from them.
    """
    args = exp.flags
    mm_vae = exp.mm_vae
    mm_vae.eval()
    subsets = exp.subsets

    n_train_samples = exp.flags.num_training_samples_lr
    train_loader = DataLoader(exp.dataset_train, batch_size=args.batch_size, shuffle=True,
                              num_workers=args.dataloader_workers)

    training_steps = exp.flags.steps_per_training_epoch

    data_train = {
        s_key: torch.Tensor()
        for s_key in subsets
    }
    all_labels = torch.Tensor()
    log.info(f"Creating {training_steps} batches of the latent representations for the classifier.")
    for it, (batch_d, batch_l) in tqdm(enumerate(train_loader), total=len(train_loader),
                                       postfix='creating_train_lr'):
        """
        Constructs the training set (labels and inferred subsets) for the classifier training.
        """
        batch_d = {k: v.to(exp.flags.device) for k, v in batch_d.items()}
        _, joint_latent = mm_vae.module.inference(batch_d) if args.distributed else mm_vae.inference(batch_d)

        lr_subsets = joint_latent.subsets
        all_labels = torch.cat((all_labels, batch_l), 0)
        for key in lr_subsets:
            data_train[key] = torch.cat((data_train[key], joint_latent.get_lr_data(key).cpu()), 0)

    # get random labels such that it contains both classes
    # labels, rand_ind_train = get_random_labels(all_labels.shape[0], n_train_samples, all_labels)
    # todo might need to sample such that all classes are represented equally
    rand_ind_train = np.random.randint(all_labels.shape[0], size=n_train_samples)
    labels = all_labels[rand_ind_train]
    for s_key in subsets:
        d = data_train[s_key]
        data_train[s_key] = d[rand_ind_train]
    return train_clf_lr(exp, data_train, labels)


def get_random_labels(n_samples, n_train_samples, all_labels, max_tries=1000):
    """
    The classifier needs labels from both classes to train. This function resamples "all_labels"
    until it contains examples from both classes
    """
    assert any(len(np.unique(all_labels[:, l])) > 1 for l in range(all_labels.shape[-1])), \
        'The labels must contain at least two classes to train the classifier'
    rand_ind_train = np.random.randint(n_samples, size=n_train_samples)
    labels = all_labels[rand_ind_train, :]
    tries = 1
    while any(len(np.unique(labels[:, l])) <= 1 for l in range(labels.shape[-1])):
        rand_ind_train = np.random.randint(n_samples, size=n_train_samples)
        labels = all_labels[rand_ind_train, :]
        tries += 1
        assert max_tries >= tries, f'Could not get sample containing both classes to train ' \
                                   f'the classifier in {tries} tries. Might need to increase batch_size'
    return labels, rand_ind_train


def test_clf_lr_all_subsets(clf_lr, exp):
    """
    Test the classifiers that were trained on latent representations.
    """
    args = exp.flags
    mm_vae = exp.mm_vae
    mm_vae.eval()
    subsets = exp.subsets

    d_loader = DataLoader(exp.dataset_test, batch_size=exp.flags.batch_size, shuffle=False,
                          num_workers=exp.flags.dataloader_workers, drop_last=False)

    training_steps = exp.flags.steps_per_training_epoch or len(d_loader)
    log.info(f'Creating {training_steps} batches of latent representations for classifier testing '
             f'with a batch_size of {exp.flags.batch_size}.')

    clf_predictions = {subset: torch.Tensor() for subset in subsets}

    batch_labels = torch.Tensor()

    for iteration, (batch_d, batch_l) in enumerate(d_loader):
        if iteration > training_steps:
            break
        batch_labels = torch.cat((batch_labels, batch_l), 0)

        batch_d = dict_to_device(batch_d, exp.flags.device)

        _, joint_latent = mm_vae.module.inference(batch_d) if args.distributed else mm_vae.inference(batch_d)
        lr_subsets = joint_latent.subsets
        data_test = {key: joint_latent.get_lr_data(key).cpu().data.numpy() for key in lr_subsets}

        clf_predictions_batch = classify_latent_representations(exp, clf_lr, data_test)
        clf_predictions_batch: Mapping[str, Mapping[str, np.array]]

        for subset in subsets:
            clf_predictions_batch_subset = torch.cat(tuple(
                torch.tensor(clf_predictions_batch[label][subset]).unsqueeze(1) for label in
                exp.labels), 1)

            clf_predictions[subset] = torch.cat([clf_predictions[subset], clf_predictions_batch_subset], 0)

    batch_labels = atleast_2d(batch_labels, -1)
    results = {}
    for subset in clf_predictions:
        # calculate metrics
        metrics = exp.metrics(clf_predictions[subset], batch_labels, str_labels=exp.labels)
        metrics_dict = metrics.evaluate()
        results[subset] = metrics.extract_values(metrics_dict)
    log.info(f'Lr eval results: {results}')

    return results


def classify_latent_representations(exp, clf_lr: Mapping[str, Mapping[str, LogisticRegression]], data) \
        -> Mapping[str, Mapping[str, np.array]]:
    """
    Returns the classification of each subset of the powerset for each label.
    """
    clf_predictions = {}
    for label_str in exp.labels:
        clf_pred_subset = {}

        for s_key, data_rep in data.items():
            # get the classifier for the subset
            clf_lr_rep = clf_lr[label_str][s_key]

            clf_pred_subset[s_key] = clf_lr_rep.predict(data_rep)

        clf_predictions[label_str] = clf_pred_subset
    return clf_predictions


def train_clf_lr(exp, data, labels):
    labels = np.reshape(labels, (labels.shape[0], len(exp.labels)))
    clf_lr_labels = {}
    for l, label_str in enumerate(exp.labels):
        gt = labels[:, l]
        clf_lr_reps = {}
        for s_key in data.keys():
            data_rep = data[s_key]
            clf_lr_s = LogisticRegression(random_state=0, solver='lbfgs', multi_class='auto', max_iter=1000)
            if exp.flags.dataset == 'testing':
                # when using the testing dataset, the vae data_rep might contain nans. Replace them for testing purposes
                clf_lr_s.fit(np.nan_to_num(data_rep), gt)
            else:
                clf_lr_s.fit(data_rep, gt)
            clf_lr_reps[s_key] = clf_lr_s
        clf_lr_labels[label_str] = clf_lr_reps
    return clf_lr_labels
