from AlphaGo.models.rollout import CNNRollout
arch = {'input_dim': 6} 
features = [
    "response",
    "save_atari",
    "neighbor",
    "nakade",
    "response_12d",
    "non_response_3x3"
]

rollout = CNNRollout(features, **arch)
rollout.save_model('my_model_rollout.json')
