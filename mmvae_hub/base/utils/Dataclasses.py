# -*- coding: utf-8 -*-
from dataclasses import dataclass
from typing import Mapping, Optional, Iterable

import torch
from torch import Tensor
from torch.autograd import Variable


@dataclass
class BaseLatents:
    enc_mods: dict
    joint: dict


@dataclass
class BaseDivergences:
    joint_div: float
    mods_div: Mapping[str, Tensor]


@dataclass
class Distr:
    mu: Tensor
    logvar: Tensor
    mod_strs: Optional[Iterable[str]] = None

    def reparameterize(self) -> Tensor:
        """
        Sample z from a multivariate Gaussian with diagonal covariance matrix using the
         reparameterization trick.
        """
        torch.manual_seed(42)
        std = self.logvar.mul(0.5).exp_()
        eps = Variable(std.data.new(std.size()).normal_())
        return eps.mul(std).add_(self.mu)


@dataclass
class PlanarFlowParams:
    u: Tensor
    w: Tensor
    b: Tensor


@dataclass
class EncModPlanarMixture:
    latents_class: Distr
    flow_params: PlanarFlowParams
    z0: Optional[Tensor] = None
    zk: Optional[Tensor] = None
    log_det_j: Optional[Tensor] = None
    latents_style: Optional[Distr] = None


@dataclass
class BaseEncMod:
    # latents have shape [batch_size, class_dim]
    latents_class: Distr
    latents_style: Optional[Distr] = None


@dataclass
class JointLatents:
    fusion_subsets_keys: Iterable[str]
    joint_distr: Distr
    subsets: Mapping[str, Distr]

    def get_joint_embeddings(self):
        return self.joint_distr.reparameterize()

    def get_subset_embedding(self, s_key: str):
        return self.subsets[s_key].reparameterize()


@dataclass
class JointEmbeddingPlanarMixture:
    embedding: Tensor
    mod_strs: Iterable[str]


@dataclass
class JointLatentsPlanarMixture:
    joint_embedding: JointEmbeddingPlanarMixture
    subsets: Mapping[str, Tensor]

    def get_joint_embeddings(self):
        return self.joint_embedding.embedding

    def get_subset_embedding(self, s_key: str):
        return self.subsets[s_key]


@dataclass
class BaseForwardResults:
    enc_mods: Mapping[str, BaseEncMod]
    joint_latents: JointLatents
    rec_mods: dict


@dataclass
class BaseBatchResults:
    total_loss: Tensor
    klds: Mapping[str, float]
    log_probs: dict
    joint_divergence: dict
    latents: Mapping[str, BaseEncMod]


@dataclass
class BaseTestResults(BaseBatchResults):
    joint_div: float
    prd_scores: Optional[dict] = None
    lr_eval: Optional[dict] = None
    gen_eval: Optional[dict] = None
    lhoods: Optional[dict] = None
    end_epoch: Optional[int] = None
    mean_epoch_time: Optional[float] = None
    experiment_duration: Optional[float] = None


@dataclass
class ReparamLatent:
    content: Tensor
    style: Optional[Mapping[str, Tensor]] = None
