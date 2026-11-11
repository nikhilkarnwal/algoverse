"""RGB plus speed/action risk head, independent of frozen SimLingo."""
import torch
from torch import nn


class RiskModel(nn.Module):
    def __init__(self, backbone='resnet18', pretrained=False):
        super().__init__()
        if backbone == 'tiny_smoke':
            self.encoder = nn.Sequential(nn.Conv2d(3, 8, 5, stride=4), nn.ReLU(),
                                         nn.AdaptiveAvgPool2d(1), nn.Flatten())
            width = 8
        elif backbone == 'resnet18':
            from torchvision.models import resnet18, ResNet18_Weights
            self.encoder = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1 if pretrained else None)
            width = self.encoder.fc.in_features
            self.encoder.fc = nn.Identity()
            for param in self.encoder.parameters():
                param.requires_grad = False
        else:
            raise ValueError('Unknown backbone')
        self.backbone = backbone
        self.head = nn.Sequential(nn.Linear(width + 6, 128), nn.ReLU(), nn.Linear(128, 2))

    def train(self, mode=True):
        super().train(mode)
        if self.backbone == 'resnet18':
            self.encoder.eval()  # Frozen BatchNorm statistics too.
        return self

    def forward(self, rgb, vector):
        return self.head(torch.cat((self.encoder(rgb), vector), dim=1))
