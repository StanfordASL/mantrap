import os
import logging
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np

import mantrap.constants
from mantrap.utility.io import datetime_name, path_from_home_directory
from mantrap.utility.shaping import check_ego_trajectory, extract_ado_trajectories


def plot_scene(
    ado_trajectories: np.ndarray,
    ado_colors: List[np.ndarray],
    ego_trajectory: np.ndarray = None,
    preview_horizon: int = mantrap.constants.visualization_preview_horizon,
    axes: Tuple[Tuple[float, float], Tuple[float, float]] = (
        mantrap.constants.sim_x_axis_default,
        mantrap.constants.sim_y_axis_default,
    ),
    output_dir: str = path_from_home_directory(f"outs/{datetime_name()}"),
):
    """Visualize simulation scene using matplotlib library.
    Thereby the ados as well as the ego in at the current time are plotted while their future trajectories
    and their state histories are indicated. Their orientation is shown using an arrow pointing in their direction
    of orientation.
    :param ego_trajectory: planned ego trajectory (t_horizon, 6).
    :param ado_trajectories: ado trajectories (num_ados, num_samples, t_horizon, 6).
    :param ado_colors: color identifier for each ado (num_ados).
    :param preview_horizon: trajectory preview time horizon (maximal value).
    :param axes: position space dimensions [m].
    :param output_dir: output directory file path.
    """
    num_ados, num_modes, t_horizon = extract_ado_trajectories(ado_trajectories)
    assert len(ado_colors) == num_ados, "ado colors must be consistent with trajectories"
    if ego_trajectory is not None:
        assert check_ego_trajectory(ego_trajectory=ego_trajectory)
    logging.debug(f"Plotting scene with {num_ados} ados having {num_modes} modes for T = {t_horizon}")

    for t in range(t_horizon):
        fig, ax = plt.subplots(figsize=mantrap.constants.visualization_fig_size)

        # Plot ados.
        ado_preview = min(preview_horizon, t_horizon - t)
        for ado_i in range(num_ados):
            ado_pose = ado_trajectories[ado_i, 0, t, 0:3]
            ado_velocity = ado_trajectories[ado_i, 0, t, 4:6]
            ado_arrow_length = np.linalg.norm(ado_velocity) / mantrap.constants.sim_speed_max * 0.5
            ado_color = ado_colors[ado_i]
            ado_history = ado_trajectories[ado_i, 0, :t, 0:2]

            ax = _add_agent_representation(ado_pose, color=ado_color, ax=ax, arrow_length=ado_arrow_length)
            ax = _add_history(ado_history, color=ado_color, ax=ax)
            for mode_i in range(num_modes):
                ax = _add_trajectory(ado_trajectories[ado_i, mode_i, t : t + ado_preview, 0:2], color=ado_color, ax=ax)

        # Plot ego.
        if ego_trajectory is not None:
            ego_pose = ego_trajectory[t, 0:3]
            ego_color = np.array([0, 0, 1.0])
            ego_history = ego_trajectory[:t, 0:2]
            ego_preview = min(preview_horizon, ego_trajectory.shape[0] - t)
            ego_planned = ego_trajectory[t : t + ego_preview, 0:2]

            ax = _add_agent_representation(ego_pose, color=ego_color, ax=ax)
            ax = _add_history(ego_history, color=ego_color, ax=ax)
            ax = _add_trajectory(ego_planned, color=ego_color, ax=ax)

        # Plot labels, limits and grid.
        x_axis, y_axis = axes
        plt.xlabel("x [m]")
        plt.xlim(x_axis)
        plt.ylabel("y [m]")
        plt.ylim(y_axis)
        plt.minorticks_on()
        plt.grid(which="minor", alpha=0.2)
        plt.grid(which="major", alpha=0.5)

        # Save and close plot.
        os.makedirs(output_dir, exist_ok=True)
        plt.savefig(os.path.join(output_dir, f"{t:04d}.png"))
        plt.close()


def _add_agent_representation(pose: np.ndarray, color: np.ndarray, ax: plt.Axes, arrow_length: float = 0.5):
    assert pose.size == 3, "pose must be 3D (x, y, theta)"

    ado_circle = plt.Circle((pose[0], pose[1]), mantrap.constants.visualization_agent_radius, color=color, clip_on=True)
    ax.add_artist(ado_circle)

    rot = np.array([[np.cos(pose[2]), -np.sin(pose[2])], [np.sin(pose[2]), np.cos(pose[2])]])
    darrow = rot.dot(np.array([1, 0])) * arrow_length
    head_width = max(0.02, arrow_length / 10)
    plt.arrow(pose[0], pose[1], darrow[0], darrow[1], head_width=head_width, head_length=0.1, fc="k", ec="k")
    return ax


def _add_trajectory(trajectory: np.ndarray, color: np.ndarray, ax: plt.Axes):
    assert len(trajectory.shape) == 2, "trajectory must have shape (N, state_length)"
    ax.plot(trajectory[:, 0], trajectory[:, 1], color=color, linestyle="-", linewidth=0.6, alpha=1.0)
    return ax


def _add_history(history: np.ndarray, color: np.ndarray, ax: plt.Axes):
    assert len(history.shape) == 2, "history must have shape (M, state_length)"
    ax.plot(history[:, 0], history[:, 1], color=color, linestyle="-.", linewidth=0.6, alpha=0.6)
    return ax
