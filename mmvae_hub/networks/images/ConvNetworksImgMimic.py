import torch
import torch.nn as nn

from mmvae_hub.networks.images.CheXNet import DenseNetFeatureExtractor
from mmvae_hub.networks.images.DataGeneratorImg import DataGeneratorImg
from mmvae_hub.networks.images.FeatureExtractorImg import FeatureExtractorImg
from mmvae_hub.networks.utils.FeatureCompressor import LinearFeatureCompressor


def get_feature_extractor_img(flags):
    if flags.feature_extractor_img == 'resnet':
        feature_extractor = FeatureExtractorImg(flags)
    elif flags.feature_extractor_img == 'densenet':
        feature_extractor = DenseNetFeatureExtractor(flags)
    else:
        raise NotImplementedError
    return feature_extractor


class EncoderImg(nn.Module):
    def __init__(self, flags, style_dim=None):
        super(EncoderImg, self).__init__()
        self.flags = flags
        self.feature_extractor = get_feature_extractor_img(flags)
        self.feature_compressor = LinearFeatureCompressor(5 * flags.DIM_img,
                                                          0,
                                                          flags.class_dim)

    def forward(self, x_img):
        h_img = self.feature_extractor(x_img)

        mu_content, logvar_content = self.feature_compressor(h_img)
        return None, None, mu_content, logvar_content


class DecoderImg(nn.Module):
    def __init__(self, flags, style_dim=None):
        super(DecoderImg, self).__init__()
        self.flags = flags
        self.feature_generator = nn.Linear(flags.class_dim, 5 * flags.DIM_img, bias=True)
        self.img_generator = DataGeneratorImg(flags)

    def forward(self, z_content):
        z = z_content
        img_feat_hat = self.feature_generator(z)
        img_feat_hat = img_feat_hat.view(img_feat_hat.size(0), img_feat_hat.size(1), 1, 1)
        img_hat = self.img_generator(img_feat_hat)

        return img_hat, torch.tensor(0.75).to(z.device)
