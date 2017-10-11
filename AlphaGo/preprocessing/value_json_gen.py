from AlphaGo.models.value import CNNValue
arch = {} # use default
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
			'zeros',
			'color'] #Adds player color, the exclusive feature for value network
value = CNNValue(features, **arch)
value.save_model('my_model_value.json')
