import os
from typing import Any, Dict

import matplotlib.pyplot as plt
import numpy as np
import torch

from mantrap.simulation.simulation import Simulation
from mantrap.utility.maths import Derivative2
from mantrap.utility.utility import build_trajectory_from_positions


def visualize_optimization(optimization_log: Dict[str, Any], env: Simulation, dir_path: str):
    assert "iter_count" in optimization_log.keys(), "iteration count must be provided in optimization dict"
    assert "x" in optimization_log.keys(), "trajectory data x must be provided in optimization dict"

    vis_keys = ["obj", "inf", "grad"]
    horizon = optimization_log["x"].shape[0]

    # For comparison in the visualization predict the behaviour of every agent in the scene for the base
    # trajectory, i.e. x0 the initial value trajectory.
    x2_base_np = np.reshape(optimization_log["x"][0], (horizon, 2))
    x2_base = torch.from_numpy(x2_base_np)
    ego_traj_base = build_trajectory_from_positions(x2_base, dt=env.dt, t_start=env.sim_time)
    ego_traj_base_np = ego_traj_base.detach().numpy()
    ado_traj_base_np = env.predict(horizon, ego_trajectory=torch.from_numpy(x2_base_np)).detach().numpy()

    for k in range(1, optimization_log["iter_count"][-1]):
        time_axis = np.linspace(env.sim_time, env.sim_time + horizon * env.dt, num=horizon)

        x2_np = np.reshape(optimization_log["x"][k], (horizon, 2))
        x2 = torch.from_numpy(x2_np)
        ego_traj = build_trajectory_from_positions(x2, dt=env.dt, t_start=env.sim_time)
        ado_traj_np = env.predict(horizon, ego_trajectory=ego_traj).detach().numpy()

        fig = plt.figure(figsize=(15, 15), constrained_layout=True)
        plt.title(f"iGrad optimization - IPOPT step {k} - Horizon {horizon}")
        plt.axis("off")
        grid = plt.GridSpec(len(vis_keys) + 3, len(vis_keys), wspace=0.4, hspace=0.3)

        # Plot current and base solution in the scene. This includes the determined ego trajectory (x) as well as
        # the resulting ado trajectories based on some simulation.
        ax = fig.add_subplot(grid[: len(vis_keys), :])
        ax.plot(x2_np[:, 0], x2_np[:, 1], label="ego_current")
        ax.plot(x2_base_np[:, 0], x2_base_np[:, 1], label="ego_base")
        # Plot current and base resulting simulated ado trajectories in the scene.
        for m in range(env.num_ados):
            ado_id, ado_color = env.ados[m].id, env.ados[m].color
            ado_pos, ado_pos_base = ado_traj_np[m, 0, :, 0:2], ado_traj_base_np[m, 0, :, 0:2]
            ax.plot(ado_pos[:, 0], ado_pos[:, 1], "--", color=ado_color, label=f"{ado_id}_current")
            ax.plot(ado_pos_base[:, 0], ado_pos_base[:, 1], "--", color=ado_color, label=f"{ado_id}_base")
        ax.set_xlim(env.axes[0])
        ax.set_ylim(env.axes[1])
        plt.grid()
        plt.legend()

        # Plot agent velocities for resulting solution vs base-line ego trajectory for current optimization step.
        ax = fig.add_subplot(grid[-3, :])
        ado_velocity_norm = np.linalg.norm(ado_traj_np[:, :, :, 3:5], axis=3)
        ado_velocity_base_norm = np.linalg.norm(ado_traj_base_np[:, :, :, 3:5], axis=3)
        for m in range(env.num_ados):
            ado_id, ado_color = env.ados[m].id, env.ados[m].color
            ax.plot(time_axis, ado_velocity_norm[m, 0, :], color=ado_color, label=f"{ado_id}_current")
            ax.plot(time_axis, ado_velocity_base_norm[m, 0, :], "--", color=ado_color, label=f"{ado_id}_base")
        ax.plot(time_axis, np.linalg.norm(ego_traj[:, 3:5], axis=1), label="ego_current")
        ax.plot(time_axis, np.linalg.norm(ego_traj_base_np[:, 3:5], axis=1), "--", label="ego_base")
        ax.set_title("velocities")
        plt.grid()
        plt.legend()

        # Plot agent accelerations for resulting solution vs base-line ego trajectory for current optimization step.
        ax = fig.add_subplot(grid[-2, :])
        dd = Derivative2(horizon=horizon, dt=env.dt)
        ado_acceleration_norm = np.linalg.norm(dd.compute(ado_traj_np[:, :, :, 0:2]), axis=3)
        ado_base_acceleration_norm = np.linalg.norm(dd.compute(ado_traj_base_np[:, :, :, 0:2]), axis=3)
        for m in range(env.num_ados):
            ado_id, ado_color = env.ados[m].id, env.ados[m].color
            ax.plot(time_axis, ado_acceleration_norm[m, 0, :], color=ado_color, label=f"{ado_id}_current")
            ax.plot(time_axis, ado_base_acceleration_norm[m, 0, :], "--", color=ado_color, label=f"{ado_id}_base")
        ax.set_title("accelerations")
        plt.grid()
        plt.legend()

        # Plot several parameter describing the optimization process, such as objective value, gradient and
        # the constraints (primal) infeasibility.
        for i, vis_key in enumerate(vis_keys):
            ax = fig.add_subplot(grid[-1, i])
            for name, data in optimization_log.items():
                if vis_key not in name:
                    continue
                ax.plot(optimization_log["iter_count"][:k], np.log(np.asarray(data[:k]) + 1e-8), label=name)
            ax.set_title(f"log_{vis_key}")
            plt.legend()
            plt.grid()

        plt.savefig(os.path.join(dir_path, f"{k}.png"), dpi=60)
        plt.close()
