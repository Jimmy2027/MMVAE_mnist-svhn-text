
import torch
import torch.nn as nn

from mimic.networks.FeatureExtractorText import FeatureExtractorText
from mimic.networks.FeatureCompressor import LinearFeatureCompressor
from mimic.networks.DataGeneratorText import DataGeneratorText


class EncoderText(nn.Module):
    def __init__(self, flags, style_dim):
        super(EncoderText, self).__init__();
        self.feature_extractor = FeatureExtractorText(flags)
        self.feature_compressor = LinearFeatureCompressor(5*flags.DIM_text,
                                                          style_dim,
                                                          flags.class_dim)

    def forward(self, x_text):
        h_text = self.feature_extractor(x_text);
        mu_style, logvar_style, mu_content, logvar_content = self.feature_compressor(h_text);
        return mu_style, logvar_style, mu_content, logvar_content;


class DecoderText(nn.Module):
    def __init__(self, flags, style_dim):
        super(DecoderText, self).__init__();
        self.flags = flags;
        self.feature_generator = nn.Linear(style_dim + flags.class_dim,
                                           5*flags.DIM_text, bias=True);
        self.text_generator = DataGeneratorText(flags)

    def forward(self, z_style, z_content):
        if self.flags.factorized_representation:
            z = torch.cat((z_style, z_content), dim=1).squeeze(-1)
        else:
            z = z_content;
        text_feat_hat = self.feature_generator(z);
        text_feat_hat = text_feat_hat.unsqueeze(-1);
        text_hat = self.text_generator(text_feat_hat)
        return [text_hat];
