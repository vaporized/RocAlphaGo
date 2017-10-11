from AlphaGo.models.policy import CNNPolicy
arch = {'filters_per_layer': 128, 'layers': 12} # args to CNNPolicy.create_network()
features = ['board',
			'ones',
			'turns_since',
			'liberties',
			'capture_size',
			'self_atari_size',
			'liberties_after',
			'ladder_capture',
			'ladder_escape',
			'sensibleness',
			'zeros'] # Important! This must match args to game_converter
policy = CNNPolicy(features, **arch)
policy.save_model('my_model.json')
