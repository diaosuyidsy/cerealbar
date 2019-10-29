"""Example of an instruction paired with agent actions."""
import numpy as np

from typing import Dict, List, Optional, Tuple

from agent.data import cereal_bar_game
from agent.data import gameplay_action
from agent.data import partial_observation
from agent.environment import agent_actions
from agent.environment import card
from agent.environment import environment_objects
from agent.environment import position
from agent.environment import state_delta
from agent.environment import terrain
from agent.environment import util as environment_util
from agent import util


class InstructionExample:
    def __init__(self,
                 instruction: List[str],
                 target_action_sequence: List[Tuple[state_delta.StateDelta, agent_actions.AgentAction,
                                                    partial_observation.PartialObservation]],
                 paired_game: cereal_bar_game.CerealBarGame,
                 example_idx_in_interaction: int,
                 leader_actions: List[List[gameplay_action.GameplayAction]],
                 index_of_first_leader_turn: int,
                 sets_made_during_instruction: List[Tuple[List[card.Card], List[card.Card]]],
                 number_of_steps_in_first_turn: int,
                 number_of_instructions_when_starting: int):
        self._instruction: List[str] = instruction
        self._target_action_sequence: List[
            Tuple[state_delta.StateDelta, agent_actions.AgentAction,
                  partial_observation.PartialObservation]] = target_action_sequence
        self._paired_game: cereal_bar_game.CerealBarGame = paired_game
        self._example_idx_in_interaction: int = example_idx_in_interaction
        self._leader_actions: List[List[gameplay_action.GameplayAction]] = leader_actions
        self._index_of_first_leader_turn: int = index_of_first_leader_turn
        self._sets_made_during_instruction: List[Tuple[List[card.Card], List[card.Card]]] = sets_made_during_instruction
        self._number_of_steps_in_first_turn: int = number_of_steps_in_first_turn
        self._number_of_instructions_when_starting: int = number_of_instructions_when_starting

        self._static_indices = None

    def get_id(self) -> str:
        return self._paired_game.get_id() + '-' + str(self._example_idx_in_interaction)

    def get_instruction(self) -> List[str]:
        return self._instruction

    def get_action_sequence(self) -> List[str]:
        return [str(x[1]) for x in self._target_action_sequence]

    def get_state_deltas(self) -> List[state_delta.StateDelta]:
        return [x[0] for x in self._target_action_sequence]

    def get_initial_cards(self) -> List[card.Card]:
        return self.get_initial_state().cards

    def get_initial_state(self) -> state_delta.StateDelta:
        return self._target_action_sequence[0][0]

    def get_static_indices(self, state_representation) -> np.array:
        if self._static_indices is None:
            self._static_indices = state_representation.static_indices(self)
        return self._static_indices

    def get_objects(self) -> List[environment_objects.EnvironmentObject]:
        return self._paired_game.get_objects()

    def get_obstacle_positions(self) -> List[position.Position]:
        obstacle_positions: List[position.Position] = list()
        for ter, hexp in self.get_hexes():
            if terrain in terrain.OBSTACLE_TERRAINS:
                obstacle_positions.append(hexp)
        for obj in self.get_objects():
            assert obj.get_type() != environment_objects.ObjectType.CARD
            obstacle_positions.append(obj.get_position())
        return obstacle_positions

    def get_hexes(self) -> List[Tuple[terrain.Terrain, position.Position]]:
        return self._paired_game.get_hexes()

    def get_visited_positions(self, include_start: bool = True, start_idx: int = 0) -> List[position.Position]:
        """Gets an ordered list of positions visited by the agent along the gold trajectory.
        
        Args:
            include_start: Whether to include the start position in the list.
            start_idx: The action index to start from.
        
        """
        if include_start:
            return list(set([delta.follower.get_position() for delta in self.get_state_deltas()[start_idx:]]))

        state: state_delta.StateDelta = self.get_state_deltas()[start_idx]
        original_position: position.Position = state.follower.get_position()
        pos_list: List[position.Position] = []
        has_moved: bool = False
        for delta in self.get_state_deltas()[start_idx:]:
            current_position = delta.follower.get_position()
            if current_position == original_position and not has_moved:
                continue
            else:
                has_moved = True
            pos_list.append(current_position)

        return list(set(pos_list))

    def get_touched_cards(self,
                          start_idx: int = 0,
                          include_start_position: bool = False,
                          allow_duplicates: bool = True) -> List[card.Card]:
        """Gets all cards touched along the gold trajectory.

        Args:
            start_idx: The first index along the trajectory to consider when computing which cards were touched.
            include_start_position: Whether to include any cards that are in the initial position.
            allow_duplicates: TODO: Not sure what this setting does actually.

        """
        if allow_duplicates:
            state: state_delta.StateDelta = self.get_state_deltas()[start_idx]
            original_card_positions: List[position.Position] = [state_card.get_position() for state_card in state.cards]

            agent_positions: List[position.Position] = self.get_visited_positions(
                include_start=include_start_position, start_idx=start_idx)
            reached_card_positions = set(original_card_positions) & set(agent_positions)

            reached_cards: List[card.Card] = list()
            for state_card in state.cards:
                if state_card.get_position() in reached_card_positions:
                    reached_cards.append(state_card)
            return reached_cards
        else:
            return get_changed_cards_along_trajectory(self.get_state_deltas())

    def get_correct_trajectory_distribution(self,
                                            weight_by_time: bool) -> np.array:

        distribution: np.array = np.zeros((1, environment_util.ENVIRONMENT_WIDTH, environment_util.ENVIRONMENT_DEPTH))
        if weight_by_time:
            path: List[position.Position] = [delta.follower.get_position() for delta in self.get_state_deltas()]

            # The weight is one over the path length, rather than the number of unique locations.
            weight_per_hex: float = 1. / len(path)
            for location in path:
                # Add the weight rather than setting it.
                distribution[0][location.x][location.y] += weight_per_hex
        else:
            correct_trajectory: List[position.Position] = self.get_visited_positions()
            weight_per_hex: float = 1. / len(correct_trajectory)

            for location in correct_trajectory:
                distribution[0][location.x][location.y] = weight_per_hex

        return distribution


def construct_game_examples(game: cereal_bar_game.CerealBarGame, max_instruction_index: int):
    # First, segment the actions by instruction.
    all_sets: List[Tuple[int, List[card.Card], List[card.Card]]] = list()

    # Segments actions into instructions
    segmented_actions: List[List[gameplay_action.GameplayAction]] = list(list())
    current_action_sequence: List[gameplay_action.GameplayAction] = list()
    instructions: List[gameplay_action.InstructionAction] = list()

    for action in game.get_actions():
        current_action_sequence.append(action)
        if isinstance(action, gameplay_action.FinishCommandAction):
            segmented_actions.append(current_action_sequence)
            current_action_sequence = list()
        elif isinstance(action, gameplay_action.InstructionAction) and action.completed():
            instructions.append(action)

    assert len(instructions) == len(segmented_actions) or len(instructions) == len(segmented_actions) - 1

    game_examples: List[InstructionExample] = list()
    current_leader_turn_idx: int = 0

    num_steps_remaining: int = 10
    buffer_size: int = 0

    current_observation: partial_observation.PartialObservation = game.get_first_partial_observation()

    for i, segmented_seq in enumerate(segmented_actions):
        follower_action_sequence: List[Tuple[state_delta.StateDelta, agent_actions.AgentAction,
                                             partial_observation.PartialObservation]] = list()
        current_leader_actions_dict: Dict[int, List[gameplay_action.GameplayAction]] = dict()
        current_sets: List[Tuple[List[card.Card], List[card.Card]]] = list()

        following: bool = False
        initial_num_steps_remaining = num_steps_remaining
        initial_buffer_size = buffer_size

        for action in segmented_seq:
            if isinstance(action, gameplay_action.MovementAction):
                if action.get_agent() == environment_objects.ObjectType.FOLLOWER:
                    follower_action_sequence.append((action.get_prior_game_info(), action.get_action(),
                                                     current_observation))

                    if not following:
                        initial_num_steps_remaining = num_steps_remaining
                        initial_buffer_size = buffer_size

                    following = True
                    num_steps_remaining -= 1
                else:
                    if following:
                        if current_leader_turn_idx not in current_leader_actions_dict:
                            current_leader_actions_dict[current_leader_turn_idx] = list()
                        current_leader_actions_dict[current_leader_turn_idx].append(action)

                set_result: Optional[Tuple[List[card.Card], List[card.Card]]] = \
                    state_delta.set_difference(action.get_prior_game_info().cards,
                                               action.get_posterior_game_info().cards)
                if set_result:
                    set_instr_idx = i if following else i - 1
                    all_sets.append((set_instr_idx, set_result[0], set_result[1]))
                    if following:
                        current_sets.append(set_result)

                # Update the observability
                current_observation = partial_observation.update_observation(current_observation,
                                                                             action.get_posterior_game_info())

            elif isinstance(action, gameplay_action.EndTurnAction):
                if action.get_agent() == environment_objects.ObjectType.FOLLOWER:
                    num_steps_remaining = 10
                else:
                    if following and current_leader_turn_idx not in current_leader_actions_dict:
                        current_leader_actions_dict[current_leader_turn_idx] = list()
                    current_leader_turn_idx += 1
            elif isinstance(action, gameplay_action.InstructionAction) and action.completed():
                if following:
                    if current_leader_turn_idx not in current_leader_actions_dict:
                        current_leader_actions_dict[current_leader_turn_idx] = list()
                    current_leader_actions_dict[current_leader_turn_idx].append(action)
                buffer_size += 1
            elif isinstance(action, gameplay_action.FinishCommandAction):
                if not following:
                    initial_buffer_size = buffer_size
                buffer_size -= 1
                follower_action_sequence.append((action.get_prior_game_info(), agent_actions.AgentAction.STOP,
                                                 current_observation))

        leader_actions_to_pass: List[List[gameplay_action.GameplayAction]] = list()
        if current_leader_actions_dict:
            first_leader_turn_idx: int = min(current_leader_actions_dict.keys())
            for j in range(first_leader_turn_idx, max(current_leader_actions_dict.keys()) + 1):
                if j not in current_leader_actions_dict:
                    leader_actions_to_pass.append(list())
                else:
                    leader_actions_to_pass.append((current_leader_actions_dict[j]))
        else:
            first_leader_turn_idx: int = current_leader_turn_idx

        from_game_actions = \
            game.get_leader_actions()[first_leader_turn_idx:first_leader_turn_idx + len(leader_actions_to_pass)]
        assert from_game_actions == leader_actions_to_pass

        example: InstructionExample = \
            InstructionExample(instructions[i].get_tokenized_instruction(),
                               follower_action_sequence,
                               game,
                               i,
                               leader_actions_to_pass,
                               first_leader_turn_idx,
                               current_sets,
                               initial_num_steps_remaining,
                               initial_buffer_size)

        game_examples.append(example)

        if len(game_examples) >= max_instruction_index >= 0:
            break

    return game_examples, all_sets


def construct_examples(games: Dict[str, cereal_bar_game.CerealBarGame],
                       max_instruction_index: int) -> Dict[str, InstructionExample]:
    examples: Dict[str, InstructionExample] = dict()

    with util.get_progressbar('constructing examples', len(games)) as pbar:
        for game_idx, (game_id, game) in enumerate(games.items()):
            game_examples, all_sets = construct_game_examples(game, max_instruction_index)
            game.set_examples(game_examples)
            game.set_sets_made(all_sets)
            for i, example in enumerate(game_examples):
                examples[game_id + '-' + str(i)] = example
            pbar.update(game_idx)

    return examples
