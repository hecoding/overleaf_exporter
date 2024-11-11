# Overleaf Exporter

A Prometheus exporter for Overleaf server (compatible with [Overleaf toolkit](https://github.com/overleaf/toolkit)).

This exporter processes the real-time.log file and exposes the following metrics:

| Metric Name | Type | Labels | Description |
|------------|------|---------|-------------|
| `realtime_exporter_info` | Info | `version` | Information about the realtime metrics exporter including its version |
| `realtime_active_connections` | Gauge | - | Number of active connections currently established |
| `realtime_project_joins_total` | Counter | `browser`, `os` | Total number of times users have joined projects, broken down by browser and operating system |
| `realtime_project_leaves_total` | Counter | `browser`, `os` | Total number of times users have left projects, broken down by browser and operating system |
| `realtime_active_projects` | Gauge | - | Number of projects currently being accessed |
| `realtime_unique_projects_total` | Counter | - | Total number of unique projects that have been accessed since exporter start |
| `realtime_active_users` | Gauge | - | Number of unique users currently connected |
| `realtime_unique_users_total` | Counter | - | Total number of unique users that have connected since exporter start |
| `realtime_session_duration_seconds` | Histogram | - | Distribution of session durations in seconds |

Tested with Toolkit version 5.1.1.

## Configuring your Overleaf instance
Make sure you added the following line to config/overleaf.rc:
```
OVERLEAF_LOG_PATH=<logs_path>
```
This configuration allows Docker Compose to mount the logs directory outside of the container. For simplicity, I use `data/logs`.

## Installation
Install the required Prometheus client:
```bash
pip install prometheus-client
```

## Usage
### Manual Execution
Run the exporter with:
```bash
python overleaf_exporter.py --logs-path <route_to_logs_path>
```
Optionally, use `--savestate-file` to specify a file for preserving state between log rotations.

### Automatic Execution (systemd)
1. Modify `overleaf_exporter.service` to specify correct paths in `ExecStart`
2. Install the service:
```bash
sudo cp overleaf_exporter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable overleaf_exporter.service
sudo systemctl start overleaf_exporter.service
```

## Troubleshooting
### Permission Issues
If your `savestate-file` is located in the Docker-mounted Overleaf logs directory and you run the toolkit with root permissions (`sudo bin/up` or `sudo bin/start`), you'll need to run the exporter with the same root permissions to write to that directory.
