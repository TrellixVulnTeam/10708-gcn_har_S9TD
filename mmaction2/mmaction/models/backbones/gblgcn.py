# Copyright (c) OpenMMLab. All rights reserved.
import torch
import torch.nn as nn
from mmcv.cnn import constant_init, kaiming_init, normal_init
from mmcv.runner import load_checkpoint
from mmcv.utils import _BatchNorm

from ...utils import get_root_logger
from ..builder import BACKBONES
from ..skeleton_gcn.utils import Graph


def zero(x):
    """return zero."""
    return 0


def identity(x):
    """return input itself."""
    return x


class GLBGCNBlock(nn.Module):
    """Applies a spatial temporal graph convolution over an input graph
    sequence.

    Args:
        in_channels (int): Number of channels in the input sequence data
        out_channels (int): Number of channels produced by the convolution
        kernel_size (tuple): Size of the temporal convolving kernel and
            graph convolving kernel
        stride (int, optional): Stride of the temporal convolution. Default: 1
        dropout (int, optional): Dropout rate of the final output. Default: 0
        residual (bool, optional): If ``True``, applies a residual mechanism.
            Default: ``True``

    Shape:
        - Input[0]: Input graph sequence in :math:`(N, in_channels, T_{in}, V)`
            format
        - Input[1]: Input graph adjacency matrix in :math:`(K, V, V)` format
        - Output[0]: Outpu graph sequence in :math:`(N, out_channels, T_{out},
            V)` format
        - Output[1]: Graph adjacency matrix for output data in :math:`(K, V,
            V)` format

        where
            :math:`N` is a batch size,
            :math:`K` is the spatial kernel size, as :math:`K == kernel_size[1]
                `,
            :math:`T_{in}/T_{out}` is a length of input/output sequence,
            :math:`V` is the number of graph nodes.
    """

    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 dropout=0,
                 residual=True):
        super().__init__()

        assert len(kernel_size) == 2
        assert kernel_size[0] % 2 == 1
        padding = ((kernel_size[0] - 1) // 2, 0)

        self.gcn = ConvTemporalGraphical(in_channels, out_channels,
                                         kernel_size[1])
        self.tcn = nn.Sequential(
            nn.BatchNorm2d(out_channels), nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, (kernel_size[0], 1),
                      (stride, 1), padding), nn.BatchNorm2d(out_channels),
            nn.Dropout(dropout, inplace=True))

        if not residual:
            self.residual = zero

        elif (in_channels == out_channels) and (stride == 1):
            self.residual = identity

        else:
            self.residual = nn.Sequential(
                nn.Conv2d(
                    in_channels,
                    out_channels,
                    kernel_size=1,
                    stride=(stride, 1)), nn.BatchNorm2d(out_channels))

        self.relu = nn.ReLU(inplace=True)

    def forward(self, x, adj_mat):
        """Defines the computation performed at every call."""
        res = self.residual(x)
        x, adj_mat = self.gcn(x, adj_mat)
        x = self.tcn(x) + res

        return self.relu(x), adj_mat


class ConvTemporalGraphical(nn.Module):
    """The basic module for applying a graph convolution.

    Args:
        in_channels (int): Number of channels in the input sequence data
        out_channels (int): Number of channels produced by the convolution
        kernel_size (int): Size of the graph convolving kernel
        t_kernel_size (int): Size of the temporal convolving kernel
        t_stride (int, optional): Stride of the temporal convolution.
            Default: 1
        t_padding (int, optional): Temporal zero-padding added to both sides
            of the input. Default: 0
        t_dilation (int, optional): Spacing between temporal kernel elements.
            Default: 1
        bias (bool, optional): If ``True``, adds a learnable bias to the
            output. Default: ``True``

    Shape:
        - Input[0]: Input graph sequence in :math:`(N, in_channels, T_{in}, V)`
            format
        - Input[1]: Input graph adjacency matrix in :math:`(K, V, V)` format
        - Output[0]: Output graph sequence in :math:`(N, out_channels, T_{out}
            , V)` format
        - Output[1]: Graph adjacency matrix for output data in :math:`(K, V, V)
            ` format

        where
            :math:`N` is a batch size,
            :math:`K` is the spatial kernel size, as :math:`K == kernel_size[1]
                `,
            :math:`T_{in}/T_{out}` is a length of input/output sequence,
            :math:`V` is the number of graph nodes.
    """

    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 t_kernel_size=1,
                 t_stride=1,
                 t_padding=0,
                 t_dilation=1,
                 bias=True):
        super().__init__()

        self.kernel_size = kernel_size
        self.conv = nn.Conv2d(
            in_channels,
            out_channels * kernel_size,
            kernel_size=(t_kernel_size, 1),
            padding=(t_padding, 0),
            stride=(t_stride, 1),
            dilation=(t_dilation, 1),
            bias=bias)

    def forward(self, x, adj_mat):
        """Defines the computation performed at every call."""
        assert adj_mat.size(0) == self.kernel_size

        x = self.conv(x)

        n, kc, t, v = x.size()
        x = x.view(n, self.kernel_size, kc // self.kernel_size, t, v)
        x = torch.einsum('nkctv,kvw->nctw', (x, adj_mat))

        return x.contiguous(), adj_mat


@BACKBONES.register_module()
class GLBGCN(nn.Module):
    """Backbone of Spatial temporal graph convolutional networks.

    Args:
        in_channels (int): Number of channels in the input data.
        graph_cfg (dict): The arguments for building the graph.
        edge_importance_weighting (bool): If ``True``, adds a learnable
            importance weighting to the edges of the graph. Default: True.
        data_bn (bool): If 'True', adds data normalization to the inputs.
            Default: True.
        pretrained (str | None): Name of pretrained model.
        **kwargs (optional): Other parameters for graph convolution units.

    Shape:
        - Input: :math:`(N, in_channels, T_{in}, V_{in}, M_{in})`
        - Output: :math:`(N, num_class)` where
            :math:`N` is a batch size,
            :math:`T_{in}` is a length of input sequence,
            :math:`V_{in}` is the number of graph nodes,
            :math:`M_{in}` is the number of instance in a frame.
    """

    def __init__(self,
                 in_channels,
                 graph_cfg,
                 edge_importance_weighting=True,
                 data_bn=True,
                 pretrained=None,
                 reduction='avg',
                 **kwargs):
        super().__init__()

        # load graph
        self.graph = Graph(**graph_cfg)
        A = torch.tensor(
            self.graph.A, dtype=torch.float32, requires_grad=False)
        self.register_buffer('A', A)
        self.in_channel = in_channels
        assert reduction in [
            'avg', 'max'], "Reduction must be either 'avg' or 'max'!"
        self.reduction = reduction

        # build networks
        spatial_kernel_size = A.size(0)
        temporal_kernel_size = 9
        kernel_size = (temporal_kernel_size, spatial_kernel_size)
        # print(A.size())
        self.data_bn = nn.BatchNorm1d(in_channels *
                                      (A.size(1)-1)) if data_bn else identity
        self.data_bn_feature = nn.BatchNorm1d(32 *
                                              (A.size(1)-1)) if data_bn else identity

        kwargs0 = {k: v for k, v in kwargs.items() if k != 'dropout'}
        self.st_gcn_networks = nn.ModuleList((
            GLBGCNBlock(
                in_channels, 64, kernel_size, 1, residual=False, **kwargs0),
            GLBGCNBlock(64, 64, kernel_size, 1, **kwargs),
            GLBGCNBlock(64, 64, kernel_size, 1, **kwargs),
            GLBGCNBlock(64, 64, kernel_size, 1, **kwargs),
            GLBGCNBlock(64, 128, kernel_size, 2, **kwargs),
            GLBGCNBlock(128, 128, kernel_size, 1, **kwargs),
            GLBGCNBlock(128, 128, kernel_size, 1, **kwargs),
            GLBGCNBlock(128, 256, kernel_size, 2, **kwargs),
            GLBGCNBlock(256, 256, kernel_size, 1, **kwargs),
            GLBGCNBlock(256, 256, kernel_size, 1, **kwargs),
        ))

        self.feature_transform = nn.ModuleList((
            nn.Linear(32, in_channels),
            nn.Linear(64, 64),
            nn.Linear(64, 64),
            nn.Linear(64, 64),
            nn.Linear(64, 64),
            nn.Linear(128, 128),
            nn.Linear(128, 128),
            nn.Linear(128, 128),
            nn.Linear(256, 256),
            nn.Linear(256, 256),
        ))

        self.feature_residue = nn.ModuleList((
            nn.Linear(32, in_channels),
            nn.Linear(32, 64),
            nn.Linear(32, 64),
            nn.Linear(32, 64),
        ))

        # initialize parameters for edge importance weighting
        if edge_importance_weighting:
            self.edge_importance = nn.ParameterList([
                nn.Parameter(torch.ones(self.A.size()))
                for i in self.st_gcn_networks
            ])
        else:
            self.edge_importance = [1 for _ in self.st_gcn_networks]

        self.pretrained = pretrained

    def init_weights(self):
        """Initiate the parameters either from existing checkpoint or from
        scratch."""
        if isinstance(self.pretrained, str):
            logger = get_root_logger()
            logger.info(f'load model from: {self.pretrained}')

            load_checkpoint(self, self.pretrained, strict=False, logger=logger)

        elif self.pretrained is None:
            for m in self.modules():
                if isinstance(m, nn.Conv2d):
                    kaiming_init(m)
                elif isinstance(m, nn.Linear):
                    normal_init(m)
                elif isinstance(m, _BatchNorm):
                    constant_init(m, 1)
        else:
            raise TypeError('pretrained must be a str or None')

    def forward(self, x):
        """Defines the computation performed at every call.
        Args:
            x (torch.Tensor): The input data.

        Returns:
            torch.Tensor: The output of the module.
        """
        x_pos = x[:, 0:self.in_channel, :, :, :]
        x_feature = x[:, self.in_channel:, :, :, :]

        x_feature = x_feature.float()
        n, c, t, v, m = x_feature.size()  # bs 32 30 25(17) 2
        x_feature = x_feature.permute(0, 4, 3, 1, 2).contiguous()  # N M V C T
        x_feature = x_feature.view(n * m, v * c, t)
        x_feature = self.data_bn_feature(x_feature)
        x_feature = x_feature.view(n, m, v, c, t)
        x_feature = x_feature.permute(0, 1, 3, 4, 2).contiguous()
        x_feature = x_feature.view(n * m, c, t, v)  # bsx2 32 30 25(17)
        # N C T V 32
        if self.reduction == 'avg':
            x_feature = torch.mean(x_feature, dim=3, keepdim=True)
        else:
            x_feature = torch.amax(x_feature, dim=3, keepdim=True)
        # bsx2 32 30 1
        # print(x_feature.size())
        x_feature_clone = x_feature
        x_feature_clone = x_feature_clone.permute(0, 2, 3, 1)

        # data normalization
        x_pos = x_pos.float()
        n, c, t, v, m = x_pos.size()  # bs 3 30 25(17) 2
        x_pos = x_pos.permute(0, 4, 3, 1, 2).contiguous()  # N M V C T
        x_pos = x_pos.view(n * m, v * c, t)
        x_pos = self.data_bn(x_pos)
        x_pos = x_pos.view(n, m, v, c, t)
        x_pos = x_pos.permute(0, 1, 3, 4, 2).contiguous()
        x_pos = x_pos.view(n * m, c, t, v)  # bsx2 3 300 25(17)

        # forward
        i = 0
        for gcn, importance, fc in zip(self.st_gcn_networks, self.edge_importance, self.feature_transform):
            x_feature = x_feature.permute(0, 2, 3, 1)
            x_feature = fc(x_feature)
            x_feature = x_feature.permute(0, 3, 1, 2)
            if i < len(self.feature_residue):
                x_feature_res = self.feature_residue[i](
                    x_feature_clone).permute(0, 3, 1, 2)
                x_feature += x_feature_res
                i += 1
            x = torch.cat((x_pos, x_feature), dim=3)
            x, _ = gcn(x, self.A * importance)
            x_pos = x[:, :, :, 0:(self.A.size(1)-1)]
            x_feature = x[:, :, :, -1].unsqueeze(3)

        return x
