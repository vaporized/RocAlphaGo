# Notes by [vapor](https://github.com/vaporized)

 - Cython files must be compiled before running the project. Command: `python setup.py build_ext --inplace`

 - Data preprocessing requires the presence of `RocAlphaGo.Data`. The command `python -m AlphaGo.preprocessing.game_converter --features all --directory tests --recurse -o debug_feature_planes.hdf5` does work.

 - `my_model_policy.json` is required for SL Policy training. Its generation code is available on the wiki page. *HOWEVER*, if you made the dataset with command in the last step, you must modify the `features` variable to include all available features: `['board','ones','turns_since','liberties','capture_size','self_atari_size','liberties_after','ladder_capture','ladder_escape','sensibleness','zeros']`.

 - SL Policy should be invoked with: `python -m AlphaGo.training.supervised_policy_trainer train training_results/sl_policy/ my_model_policy.json debug_feature_planes.hdf5 --epochs 5 --minibatch 32 --learning-rate 0.01`. The required parameters are `{train, resume}`, output directory, model specification, and training data.
 
 - Plenty of bugs caused by incompatibility of Python 2 and 3 are fixed to work on Python 3.6, which is specified in the plan. 

 - RL Policy should be invoked with: `python -m AlphaGo.training.reinforcement_policy_trainer my_model_policy.json training_results/sl_policy/policy_supervised_weights/weights.00004.hdf5 training_results/rl_policy/ --iterations 2 --game-batch 2`. The required parameters are model specification, trained weights file from SL Policy, and output directory.

 - Generate the dataset for RL value network with: `python -m AlphaGo.preprocessing.generate_value_training training_results/sl_policy/policy_supervised_weights/weights.00004.hdf5  training_results/rl_policy/weights.00002.hdf5 my_model_policy.json --n-training-pairs 500`. The required parameters are trained weights file from SL Policy, trained weights from RL Policy, and model specification. Output directory is not customizable, a file called `value_planes.hdf5` will be generated at the currect directory. Generating 10 pairs takes 3 min on my computer, 50 million in the paper is impossible.

 - RL Value should be invoked with: `python -m AlphaGo.training.reinforcement_value_trainer train training_results/rl_value/ my_model_value.json value_planes.hdf5`. Please note that the dataset needs to have sufficient samples, such that `0.05 * length` is greater than 1. An appropriate parameter should be specified at the previous step.

 
