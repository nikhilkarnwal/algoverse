"""Shadow-mode risk inference boundary; never modifies vehicle controls."""
import torch
from av_safeplan.training.data import HAZARDS, PREPROCESSING, encode
from av_safeplan.training.model import RiskModel


class ShadowRiskPredictor:
    def __init__(self, checkpoint, device='cpu'):
        payload = torch.load(checkpoint, map_location=device, weights_only=True)
        if payload['kind'] != 'reviewed_pilot':
            raise ValueError('Engineering smoke checkpoints cannot be used in driving')
        if payload['config']['preprocessing'] != PREPROCESSING:
            raise ValueError('Preprocessing contract mismatch')
        self.device = torch.device(device)
        self.model = RiskModel(payload['config']['backbone']).to(self.device)
        self.model.load_state_dict(payload['model']); self.model.eval()

    @torch.no_grad()
    def predict(self, rgb_image, speed_mps, base_action):
        rgb, vector = encode(rgb_image, speed_mps, base_action)
        probabilities = self.model(rgb[None].to(self.device), vector[None].to(self.device)).sigmoid()[0].cpu().tolist()
        return {'mode': 'shadow_only', 'risk': dict(zip(HAZARDS, probabilities)),
                'control_override': None, 'calibrated': False}
