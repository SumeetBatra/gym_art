import random
from collections import deque
from copy import deepcopy

import gym
import numpy as np


class ReplayBuffer:
    def __init__(self, control_frequency, cp_step_size=0.5, buffer_size=100):  # TODO: what is the right buffer size?
        self.control_frequency = control_frequency
        self.cp_step_size_sec = cp_step_size  # how often (seconds) a checkpoint is saved
        self.cp_step_size_freq = self.cp_step_size_sec * self.control_frequency
        self.buffer_idx = 0
        self.buffer = deque([], maxlen=buffer_size)

    def write_cp_to_buffer(self, env, obs):
        """
        A collision was found and we want to load the corresponding checkpoint from X seconds ago into the buffer to be sampled later on
        """
        env.saved_in_replay_buffer = True

        # TODO: here we should delete items from the buffer based on statistics.
        # For example, replace the item with the lowest number of collisions in the last 10 replays
        if len(self.buffer) < self.buffer.maxlen:
            self.buffer.append((env, obs))
        else:
            self.buffer[self.buffer_idx] = (env, obs)  # override existing event
        self.buffer_idx = (self.buffer_idx + 1) % self.buffer.maxlen
        print(f"Added new collision event to buffer at {self.buffer_idx}")

    def sample_event(self):
        """
        Sample an event to replay
        """
        return random.choice(self.buffer)

    def __len__(self):
        return len(self.buffer)


class ExperienceReplayWrapper(gym.Wrapper):
    def __init__(self, env, replay_buffer_sample_prob=0.0):  # TODO: change default value
        super().__init__(env)
        self.replay_buffer = ReplayBuffer(env.envs[0].control_freq)
        self.replay_buffer_sample_prob = replay_buffer_sample_prob

        self.max_episode_checkpoints_to_keep = int(3.0 / self.replay_buffer.cp_step_size_sec)  # keep only checkpoints from the last 3 seconds
        self.episode_checkpoints = deque([], maxlen=self.max_episode_checkpoints_to_keep)

        self.save_time_before_collision_sec = 1.5
        self.last_tick_added_to_buffer = -1e9

    def save_checkpoint(self, obs):
        """
        Save a checkpoint every X steps so that we may load it later if a collision was found. This is NOT the same as the buffer
        Checkpoints are added to the buffer only if we find a collision and want to replay that event later on
        """
        self.episode_checkpoints.append((deepcopy(self.env), deepcopy(obs)))

    def step(self, action):
        obs, rewards, dones, infos = self.env.step(action)

        if self.env.use_replay_buffer and self.env.activate_replay_buffer and not self.env.saved_in_replay_buffer \
                and self.env.envs[0].tick % self.replay_buffer.cp_step_size_freq == 0:
            self.save_checkpoint(obs)

        if self.env.last_step_unique_collisions.any() and self.env.use_replay_buffer and self.env.activate_replay_buffer \
                and self.env.envs[0].tick > self.env.collisions_grace_period_seconds * self.env.envs[0].control_freq and not self.saved_in_replay_buffer:

            if self.env.envs[0].tick - self.last_tick_added_to_buffer > 2 * self.env.envs[0].control_freq:
                # added this check to avoid adding a lot of collisions from the same episode to the buffer

                steps_ago = int(self.save_time_before_collision_sec / self.replay_buffer.cp_step_size_sec)
                if steps_ago > len(self.episode_checkpoints):
                    print(f"Tried to read past the boundary of checkpoint_history. Steps ago: {steps_ago}, episode checkpoints: {len(self.episode_checkpoints)}, {self.env.envs[0].tick}")
                else:
                    env, obs = self.episode_checkpoints[-steps_ago]
                    self.replay_buffer.write_cp_to_buffer(env, obs)
                    self.env.collision_occurred = False  # this allows us to add a copy of this episode to the buffer once again if another collision happens

                    self.last_tick_added_to_buffer = self.env.envs[0].tick

        return obs, rewards, dones, infos

    def reset(self):
        self.last_tick_added_to_buffer = -1e9
        self.episode_checkpoints = deque([], maxlen=self.max_episode_checkpoints_to_keep)

        if np.random.uniform(0, 1) < self.replay_buffer_sample_prob and self.replay_buffer and self.env.activate_replay_buffer \
                and len(self.replay_buffer) > 0:
            env, obs = self.replay_buffer.sample_event()
            replayed_env = deepcopy(env)
            replayed_env.scene = self.env.scene
            self.env = replayed_env
            print("Replaying previous episode")
            return obs
        else:
            obs = self.env.reset()
            self.env.saved_in_replay_buffer = False
            return obs
