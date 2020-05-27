import typing

import torch

import mantrap.environment

from .base import PureObjectiveModule


class InteractionProbabilityModule(PureObjectiveModule):
    """Loss based on unconditioned probability value in distribution conditioned on ego motion.

    The general idea of an interactive objective module is to compare the ado trajectory distributions as if
    no ego/robot would be in the scene with the distributions conditioned on the robot trajectory, in order to
    drive the robot's trajectory optimisation to some state in which the ados are (in average) minimally
    disturbed by the robots motion. For general ado trajectory probability distributions including multi-modality,
    this is not a trivial problem. In fact its is not analytically solved for most multi-modal distributions.
    However in the following some common approaches:

    1) KL-Divergence: The KL-Divergence expresses the similarity some distribution q with respect to another
    distribution p:

    .. math::D_{KL} = \\int q(x) log \\frac{q(x)}{p(x)} dx

    While this is a well-defined and  commonly used similarity measure for "simple" distributions for more
    complex ones, such as GMM (e.g. as Trajectron's output) it is not analytically defined. Methods to
    approximate the KL-Divergence for GMMs embrace Monte Carlo sampling, optimisation (itself) and several
    more which however are not computationally feasible for an online application, especially since the
    objective's gradient has to be computed. Other methods simply the real GMM to a single Gaussian, by a
    weighted average over its parameters, which is a) not guaranteed to be a meaningful distribution and
    b) looses the advantages of predicting multi-modal distributions in the first place.

    Especially for trajectron one could also not use the output distribution, but some intermediate (maybe
    simpler distribution) instead, e.g. the latent space, but this one does not depend on the ego trajectory
    so cannot be used for its optimisation.

    2) Unconditioned path projection: Another approach is to compute (and maximize) the probability of the
    mean unconditioned trajectories (mode-wise) appearing in the conditioned distribution. While it only takes
    into account the mean values (and weights) it is very efficient to compute while still taking the full
    conditioned distribution into account and has shown to be "optimise-able" in the training of Trajectron.
    Since the distributions itself are constant, while the sampled trajectories vary, the objective is also
    constant regarding the same scenario, which also improves its "optimise-ability".

    :param env: solver's environment environment for predicting the behaviour without interaction.
    """
    _env: mantrap.environment.base.ProbabilisticEnvironment  # typing hint

    def __init__(self, env: mantrap.environment.base.ProbabilisticEnvironment, t_horizon: int, weight: float = 1.0,
                 **unused):
        super(InteractionProbabilityModule, self).__init__(env=env, t_horizon=t_horizon, weight=weight)

        # Determine mean trajectories and weights of unconditioned distribution. Therefore compute the
        # unconditioned distribution and store the resulting values in an ado-id-keyed dictionary.
        if not env.is_deterministic and env.num_ados > 0:
            _, dist = env.build_connected_graph_wo_ego(t_horizon, return_distribution=True)
            self._mus_un_conditioned = {key: x.mus.view(-1, t_horizon, 2).detach()
                                        for key, x in dist.items()}  # type: typing.Dict[str, torch.Tensor]
            self._pis_un_conditioned = {key: x.log_pis.view(-1, t_horizon).detach()
                                        for key, x in dist.items()}  # type: typing.Dict[str, torch.Tensor]

    def objective_core(self, ego_trajectory: torch.Tensor, ado_ids: typing.List[str], tag: str
                       ) -> typing.Union[torch.Tensor, None]:
        """Determine objective value core method.

        :param ego_trajectory: planned ego trajectory (t_horizon, 5).
        :param ado_ids: ghost ids which should be taken into account for computation.
        :param tag: name of optimization call (name of the core).
        """
        # The objective can only work if any ado agents are taken into account, otherwise return None.
        # If the environment is not deterministic the output distribution is not defined, hence return None.
        if len(ado_ids) == 0 or self._env.num_ghosts == 0 or self.env.is_deterministic:
            return None

        # Compute the conditioned distribution. Then for every ado in the ado_ids`-list determine the `
        # probability of occurring in this distribution, using the distributions core methods.
        _, distribution = self._env.build_connected_graph(ego_trajectory, return_distribution=True)
        objective = torch.zeros(1)
        for ado_id in ado_ids:
            p = distribution[ado_id].log_prob(self._mus_un_conditioned[ado_id])
            w = self._pis_un_conditioned[ado_id]
            objective += torch.sum(torch.mul(w, p))

        return torch.sum(ego_trajectory[:, 0:2])

    def gradient_condition(self) -> bool:
        """Condition for back-propagating through the objective/constraint in order to obtain the
        objective's gradient vector/jacobian (numerically). If returns True and the ego_trajectory
        itself requires a gradient, the objective/constraint value, stored from the last computation
        (`_current_`-variables) has to require a gradient as well.

        If the internal environment is itself differentiable with respect to the ego (trajectory) input, the
        resulting objective value must have a gradient as well.
        """
        return self._env.is_differentiable_wrt_ego

    ###########################################################################
    # Objective Properties ####################################################
    ###########################################################################
    @property
    def name(self) -> str:
        return "interaction_prob"
