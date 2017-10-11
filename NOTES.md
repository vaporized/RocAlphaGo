# Notes by [vapor](https://github.com/vaporized)

 - Cython files must be compiled before running the project. Command: `python setup.py build_ext --inplace`

 - Data preprocessing requires the presence of `RocAlphaGo.Data`. The command `python -m AlphaGo.preprocessing.game_converter --features all --directory tests --recurse -o debug_feature_planes.hdf5` does work.

 - `my_model.json` is required for SL Policy training. Its generation code is available on the wiki page. *HOWEVER*, if you made the dataset with command in the last step, you must modify the `features` variable to include all available features: `['board','ones','turns_since','liberties','capture_size','self_atari_size','liberties_after','ladder_capture','ladder_escape','sensibleness','zeros']`.

 - SL Policy should be invoked with: `python -m AlphaGo.training.supervised_policy_trainer train training_results/ my_model.json debug_feature_planes.hdf5 --epochs 5 --minibatch 32 --learning-rate 0.01`

 -Plenty of bugs caused by incompatibility of Python 2 and 3 are fixed to work on Python 3.6, which is specified in the plan. 

 
