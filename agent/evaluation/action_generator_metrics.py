from __future__ import annotations

import numpy as np
from typing import TYPE_CHECKING

from agent import util
from agent.evaluation import evaluation_logger
from agent.evaluation import metric
from agent.simulation import python_game
from agent.simulation import server
from agent.simulation import unity_game

if TYPE_CHECKING:
    from typing import Dict, List
    from agent.config import evaluation_args
    from agent.config import game_args
    from agent.data import cereal_bar_game
    from agent.data import instruction_example
    from agent.model.model_wrappers import action_generator_model_wrapper


def execution_accuracies(model: action_generator_model_wrapper.ActionGeneratorModelWrapper,
                         game_arguments: game_args.GameArgs,
                         evaluation_arguments: evaluation_args.EvaluationArgs,
                         instruction_examples: List[instruction_example.InstructionExample] = None,
                         game_examples: List[cereal_bar_game.CerealBarGame] = None):

    logger: evaluation_logger.EvaluationLogger = evaluation_logger.EvaluationLogger(
        evaluation_arguments.get_evaluation_results_filename())

    metric_dict: Dict[metric.Metric, List[float]] = {metric.Metric.SCORE: list(),
                                                     metric.Metric.CARD_ACCURACY: list(),
                                                     metric.Metric.SEQUENCE_ACCURACY: list(),
                                                     metric.Metric.RELAXED_ENVIRONMENT_ACCURACY: list(),
                                                     metric.Metric.AGENT_DISTANCE: list(),
                                                     metric.Metric.EXACT_ENVIRONMENT_ACCURACY: list(),
                                                     metric.Metric.PROPORTION_POINTS_CASCADING: list(),
                                                     metric.Metric.PROPORTION_FOLLOWED_CASCADING: list(),
                                                     metric.Metric.PROPORTION_VALID_CASCADING: list()}

    game_server_socket = None
    if evaluation_arguments.use_unity():
        game_server_socket: server.ServerSocket = server.ServerSocket(game_arguments.get_ip_address(),
                                                                      game_arguments.get_port())
        game_server_socket.start_unity()

    if instruction_examples:
        with util.get_progressbar('evaluating individual instructions...', len(instruction_examples)) as pbar:
            for i, example in enumerate(instruction_examples):
                pbar.update(i)

                logger.log('***** Example #' + example.get_id() + ' *****')
                logger.log('Instruction: ' + ' '.join(example.get_instruction()))

                # Set up the server and reset the state
                if evaluation_arguments.use_unity():
                    game_server: unity_game.UnityGame = unity_game.UnityGame(game_arguments,
                                                                             game_server_socket,
                                                                             seed=example.get_seed(),
                                                                             auto_end_turn=True)
                else:
                    game_server: python_game.PythonGame = python_game.PythonGame(game_arguments,
                                                                                 example.get_hexes(),
                                                                                 example.get_objects(),
                                                                                 example.get_initial_state(),
                                                                                 leader_actions=None)

                game_server.reset_state(leader_actions=example.get_leader_actions(),
                                        state=example.get_initial_state(),
                                        expected_sets=example.get_expected_sets(),
                                        num_steps_remaining=example.get_number_of_moves_in_first_turn())
                game_server.send_command(' '.join(example.get_instruction()))

                # Run inference
                predicted_sequence, auxiliary_predictions, _ = \
                    model.get_predictions(example, game_server=game_server, evaluation_arguments=evaluation_arguments,
                                          logger=logger)

                predicted_sequence = [str(action) for action in predicted_sequence]

                if game_server.valid_state():
                    game_server.finish_all_leader_actions()

                # Compute the metrics
                metric_dict[metric.Metric.SCORE].append(game_server.get_score())
                for metric_name in metric.INSTRUCTION_METRICS:
                    resulting_metric: float = metric.compute_instruction_metric(
                        metric_name, example, predicted_sequence, game_server.get_game_info(),
                        evaluation_arguments.get_distance_threshold())

                    metric_dict[metric_name].append(resulting_metric)

    if game_examples:
        raise ValueError('Full-game inference is not yet supported.')

    means_dict: Dict[metric.Metric, float] = dict()
    for metric_name, values in metric_dict.items():
        if values:
            means_dict[metric_name] = np.mean(np.array(values)).item()

            if 'ACCURACY' in str(metric_name):
                means_dict[metric_name] = 100. * means_dict[metric_name]

    logger.close()

    if evaluation_arguments.use_unity():
        game_server_socket.close()

    return means_dict