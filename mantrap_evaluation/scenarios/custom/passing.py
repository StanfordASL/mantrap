import typing

import mantrap
import torch

import mantrap_evaluation.scenarios.api


def custom_passing(env_type: mantrap.environment.base.GraphBasedEnvironment.__class__
                   ) -> typing.Tuple[mantrap.environment.base.GraphBasedEnvironment,
                                     torch.Tensor,
                                     typing.Union[typing.Dict[str, torch.Tensor], None]]:
    """Scenario passing.

    One agent walks in between the robot and its goal state, so that the robot either has to wait or
    surpass behind the pedestrian.
    """
    ego_state = torch.tensor([0, 0, 0, 0])
    ego_goal = torch.tensor([8, 0])
    ado_histories = torch.tensor([5, 2, 0, -1, 0]).unsqueeze(dim=0)
    ado_goals = torch.tensor([5, -4])

    return mantrap_evaluation.scenarios.api.create_environment(
        config_name="custom_passing",
        env_type=env_type,
        ado_histories=[ado_histories],
        ego_type=mantrap.agents.DoubleIntegratorDTAgent,
        ego_state=ego_state,
        ado_goals=[ado_goals],
    ), ego_goal, None