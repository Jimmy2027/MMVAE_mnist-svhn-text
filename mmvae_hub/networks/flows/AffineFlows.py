# -*- coding: utf-8 -*-

import FrEIA.framework as Ff
import FrEIA.modules as Fm
from torch import nn

from mmvae_hub.utils.Dataclasses import PlanarFlowParams


class AffineFlow(nn.Module):
    """Affine coupling Flow"""

    def __init__(self, class_dim, num_flows, coupling_dim):
        super().__init__()

        self.coupling_dim = coupling_dim
        # a simple chain of operations is collected by ReversibleSequential
        # see here for more details: https://vll-hd.github.io/FrEIA/_build/html/FrEIA.modules.html#coupling-blocks
        self.flow = Ff.SequenceINN(class_dim)
        for _ in range(num_flows):
            self.flow.append(Fm.AllInOneBlock, subnet_constructor=self.subnet_fc, permute_soft=True)

    def forward(self, z0, flow_params=None):
        zk, log_det_jacobian = self.flow(z0)

        return z0, zk, log_det_jacobian

    def rev(self, zk):
        return self.flow(zk, rev=True)

    def get_flow_params(self, h=None):
        # for compat with amortized flows
        return PlanarFlowParams(**{k: None for k in ['u', 'w', 'b']})

    def subnet_fc(self, dims_in, dims_out):
        return nn.Sequential(nn.Linear(dims_in, self.coupling_dim), nn.ReLU(),
                             nn.Linear(self.coupling_dim, dims_out))