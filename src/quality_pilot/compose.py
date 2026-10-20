from __future__ import annotations

import subprocess
from pathlib import Path


ARTIFACTS_CONTAINER_PATH = "/quality-pilot-artifacts"


class DockerCompose:
    def __init__(self, compose_file: Path, project_name: str) -> None:
        self.project_name = project_name
        self.base_args = [
            "docker",
            "compose",
            "--file",
            str(compose_file),
            "--project-name",
            project_name,
        ]

    def config_check(self, output_path: Path) -> int:
        return self.run([*self.base_args, "config", "--quiet"], output_path, timeout=60)

    def start(self, services: tuple[str, ...], output_path: Path, timeout: int) -> int:
        return self.run(
            [
                *self.base_args,
                "up",
                "--detach",
                "--build",
                "--wait",
                "--wait-timeout",
                str(timeout),
                *services,
            ],
            output_path,
            timeout=timeout,
        )

    def test(
        self,
        service: str,
        command: tuple[str, ...],
        artifacts_dir: Path,
        output_path: Path,
        timeout: int,
    ) -> int:
        expanded_command = [
            part.replace("{artifacts}", ARTIFACTS_CONTAINER_PATH) for part in command
        ]
        return self.run(
            [
                *self.base_args,
                "run",
                "--rm",
                "--no-deps",
                "--volume",
                f"{artifacts_dir.resolve()}:{ARTIFACTS_CONTAINER_PATH}",
                service,
                *expanded_command,
            ],
            output_path,
            timeout=timeout,
        )

    def logs(self, output_path: Path) -> int:
        return self.run(
            [*self.base_args, "logs", "--no-color", "--timestamps"],
            output_path,
            timeout=60,
        )

    def stop(self, output_path: Path) -> int:
        result = self.run(
            [*self.base_args, "down", "--remove-orphans"],
            output_path,
            timeout=120,
        )
        if result != 0:
            return result

        volume_list = output_path.with_name("project-volumes.txt")
        result = self.run(
            [
                "docker",
                "volume",
                "ls",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={self.project_name}",
            ],
            volume_list,
            timeout=30,
        )
        if result != 0:
            return result
        volumes = volume_list.read_text(encoding="utf-8").split()
        if not volumes:
            return 0
        return self.run(["docker", "volume", "rm", *volumes], output_path, timeout=60)

    @staticmethod
    def run(args: list[str], output_path: Path, timeout: int | None = None) -> int:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output_path.open("w", encoding="utf-8") as output_file:
                try:
                    completed = subprocess.run(
                        args,
                        stdout=output_file,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    output_file.write(f"\nQuality Pilot: command timed out after {timeout} seconds.\n")
                    return 124
        except FileNotFoundError as exc:
            output_path.write_text(f"Unable to start command: {exc}\n", encoding="utf-8")
            return 127
        return completed.returncode
