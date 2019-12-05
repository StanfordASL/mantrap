from typing import Any, Dict, List, Tuple

import numpy as np
import torch

import mantrap.constants
from mantrap.agents.agent import Agent
from mantrap.agents import DoubleIntegratorDTAgent
from mantrap.simulation.abstract import ForcesBasedSimulation


class DistanceFieldSimulation(ForcesBasedSimulation):
    def __init__(
        self,
        ego_type: Agent.__class__ = None,
        ego_kwargs: Dict[str, Any] = None,
        x_axis: Tuple[float, float] = mantrap.constants.sim_x_axis_default,
        y_axis: Tuple[float, float] = mantrap.constants.sim_y_axis_default,
        dt: float = mantrap.constants.sim_dt_default,
    ):
        super(DistanceFieldSimulation, self).__init__(ego_type, ego_kwargs, x_axis=x_axis, y_axis=y_axis, dt=dt)

    def add_ado(self, **ado_kwargs):
        """Add another DTV ado to the simulation. Since this simulation is based on forces the control input
        of each agent is a force, equivalent to some acceleration. Therefore it must be a double integrator. """
        super(DistanceFieldSimulation, self)._add_ado(DoubleIntegratorDTAgent, **ado_kwargs)

    def build_graph(self, ados: List[Agent] = None, ego_state: np.ndarray = None) -> Dict[str, torch.Tensor]:
        """Graph:
        --> Input = position of ados and ego state
        --> Output = Force acting on every ado"""
        ados = self._ados if ados is None else ados
        if ego_state is not None:
            assert ego_state.size >= 2, "ego state must contain (x, y) - position"

        # Define simulation parameters (as defined in the paper).
        num_ados = len(ados)
        sigma = 0.1  # [m] repulsive field exponent constant.

        def _repulsive_force(alpha_position: torch.Tensor, beta_position: torch.Tensor):
            relative_distance = torch.sub(alpha_position, beta_position)
            norm_relative_distance = torch.max(torch.norm(relative_distance), torch.from_numpy(np.array([1e-10])))
            direction = torch.div(relative_distance, norm_relative_distance)
            return torch.exp(-norm_relative_distance / sigma) * direction

        # Graph initialization - Add ados and ego to graph (position only).
        graph = {}
        for i in range(num_ados):
            iid = ados[i].id
            graph[f"{iid}_position"] = torch.tensor(ados[i].position.astype(float))
            graph[f"{iid}_position"].requires_grad = True
        if ego_state is not None:
            graph["ego_position"] = torch.tensor(ego_state[0:2].astype(float))
            graph["ego_position"].requires_grad = True

        # Make graph with resulting force as an output.
        for i in range(num_ados):
            iid = ados[i].id
            graph[f"{iid}_force"] = torch.zeros(2)

            # Interactive force - Repulsive potential field by every other agent.
            for j in range(num_ados):
                jid = ados[j].id
                if iid == jid:
                    continue
                f_repulsive = _repulsive_force(graph[f"{iid}_position"], graph[f"{jid}_position"])
                graph[f"{iid}_force"] = torch.sub(graph[f"{iid}_force"], f_repulsive)

            # Interactive force w.r.t. ego - Repulsive potential field.
            if ego_state is not None:
                f_repulsive = _repulsive_force(graph[f"{iid}_position"], graph["ego_position"])
                graph[f"{iid}_force"] = torch.sub(graph[f"{iid}_force"], f_repulsive)

            # Summarize (standard) graph elements.
            graph[f"{iid}_force_norm"] = torch.norm(graph[f"{iid}_force"])

        # Graph health check.
        assert self.graph_check(graph=graph)

        return graph
