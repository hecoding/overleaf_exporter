import json
import time
from datetime import datetime
from pathlib import Path
from prometheus_client import start_http_server, Counter, Gauge, Histogram, Info
import re

# Compile regex patterns for user agent parsing
browser_pattern = re.compile(r'(Chrome|Safari|Firefox)')
os_pattern = re.compile(r'(Windows NT|Mac OS X)')


def parse_user_agent(user_agent):
    browser = browser_pattern.search(user_agent)
    os = os_pattern.search(user_agent)
    return (
        browser.group(1) if browser else "Other",
        os.group(1) if os else "Other"
    )


def read_log(path):
    logs = []
    with open(path, 'r') as f:
        for line in f:
            try:
                log = json.loads(line)
                logs.append(log)
            except json.JSONDecodeError:
                continue
    return logs


def parse_time(time_str):
    return datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ").timestamp()


class RealtimeMetrics:
    VERSION = "1.0"

    def __init__(self):
        # Version info
        self.info = Info(
            'realtime_exporter',
            'Information about the realtime metrics exporter'
        )
        self.info.info({'version': self.VERSION})

        # Active connections gauge
        self.active_connections = Gauge(
            'realtime_active_connections', 
            'Number of active connections'
        )

        # Project metrics
        self.project_joins = Counter(
            'realtime_project_joins_total',
            'Total number of project joins',
            ['browser', 'os']
        )
        self.project_leaves = Counter(
            'realtime_project_leaves_total',
            'Total number of project leaves',
            ['browser', 'os']
        )
        self.active_projects = Gauge(
            'realtime_active_projects',
            'Number of projects currently being accessed'
        )
        self.unique_projects = Counter(
            'realtime_unique_projects_total',
            'Total number of unique projects accessed'
        )

        # User metrics
        self.active_users = Gauge(
            'realtime_active_users',
            'Number of unique users currently connected'
        )
        self.unique_users = Counter(
            'realtime_unique_users_total',
            'Total number of unique users'
        )

        # Session duration
        self.session_duration = Histogram(
            'realtime_session_duration_seconds',
            'Session duration in seconds',
            buckets=[30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 14400, 18000, 21600, 25200, 28800, 32400, 36000, 39600, 43200]  # Up to 12h
        )

        # Internal state
        self.active_sessions = {}    # {client_id: {'start_time': timestamp, 'user_id': id}}
        self.project_users = {}      # {project_id: set(user_ids)}
        self.seen_projects = set()   # All projects ever seen
        self.seen_users = set()      # All users ever seen
        self.last_time = 0

    @staticmethod
    def get_counter_values(counter):
        """Helper function to get counter values by labels"""
        values = {}
        for labels, metric in counter._metrics.items():
            # Convert label tuple to string key
            label_key = '_'.join(labels)
            values[label_key] = metric._value.get()
        return values

    def save_state(self, filepath):
        """Save current state to a JSON file"""

        state = {
            'active_sessions': self.active_sessions,
            'project_users': {k: list(v) for k, v in self.project_users.items()},  # Convert sets to lists
            'seen_projects': list(self.seen_projects),
            'seen_users': list(self.seen_users),
            'last_time': self.last_time,
            # Save counter values
            'counters': {
                'project_joins': self.get_counter_values(self.project_joins),
                'project_leaves': self.get_counter_values(self.project_leaves),
                'unique_projects': self.unique_projects._value.get(),
                'unique_users': self.unique_users._value.get(),
                # Get histogram values directly from _sum and _buckets
                'session_duration': {
                    'sum': self.session_duration._sum.get(),
                    'buckets': [bucket.get() for bucket in self.session_duration._buckets]
                }
            }
        }

        with open(filepath, 'w') as f:
            json.dump(state, f)

    def load_state(self, filepath):
        """Load state from a JSON file"""
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)

            self.active_sessions = state['active_sessions']
            self.project_users = {k: set(v) for k, v in state['project_users'].items()}  # Convert lists back to sets
            self.seen_projects = set(state['seen_projects'])
            self.seen_users = set(state['seen_users'])
            self.last_time = state['last_time']

            # Restore counter values
            for browser_os, value in state['counters']['project_joins'].items():
                browser, os = browser_os.split('_')
                self.project_joins.labels(browser=browser, os=os)._value.set(value)

            for browser_os, value in state['counters']['project_leaves'].items():
                browser, os = browser_os.split('_')
                self.project_leaves.labels(browser=browser, os=os)._value.set(value)

            self.unique_projects._value.set(state['counters']['unique_projects'])
            self.unique_users._value.set(state['counters']['unique_users'])

            # Restore histogram values
            hist_data = state['counters']['session_duration']
            self.session_duration._sum.set(hist_data['sum'])
            for i, value in enumerate(hist_data['buckets']):
                self.session_duration._buckets[i].set(value)

            # Update gauges based on loaded state
            self.active_connections.set(len(self.active_sessions))
            self.active_projects.set(len(self.project_users))

            # Update active users gauge
            unique_users = set()
            for users in self.project_users.values():
                unique_users.update(users)
            self.active_users.set(len(unique_users))

            return True
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            print(f"Error loading state from {filepath}: {e}")
            return False

    def process_log(self, log):
        if 'msg' not in log or 'userId' not in log or 'projectId' not in log:
            return

        browser, os = parse_user_agent(log.get('userAgent', ''))
        client_id = log.get('clientId')
        user_id = log['userId']
        project_id = log['projectId']

        # Track unique users and projects
        if user_id not in self.seen_users:
            self.seen_users.add(user_id)
            self.unique_users.inc()

        if project_id not in self.seen_projects:
            self.seen_projects.add(project_id)
            self.unique_projects.inc()

        if log['msg'] == 'user joining project':
            # Update counters and track session start
            self.project_joins.labels(browser=browser, os=os).inc()
            self.active_sessions[client_id] = {
                'start_time': parse_time(log['time']),
                'user_id': user_id
            }

            # Track project users
            if project_id not in self.project_users:
                self.project_users[project_id] = set()
            self.project_users[project_id].add(user_id)

        elif log['msg'] == 'client leaving project':
            # Update counters and calculate session duration
            self.project_leaves.labels(browser=browser, os=os).inc()
            if client_id in self.active_sessions:
                start_time = self.active_sessions[client_id]['start_time']
                duration = parse_time(log['time']) - start_time
                self.session_duration.observe(duration)
                del self.active_sessions[client_id]

            # Update project users
            if project_id in self.project_users:
                self.project_users[project_id].discard(user_id)
                if not self.project_users[project_id]:
                    del self.project_users[project_id]

        # Update gauges
        self.active_connections.set(len(self.active_sessions))
        self.active_projects.set(len(self.project_users))

        # Count unique active users
        unique_users = set()
        for users in self.project_users.values():
            unique_users.update(users)
        self.active_users.set(len(unique_users))


def main(logs_path='data/logs', polling_time=60, savestate_file=None, port=8000):
    log_path = Path(logs_path) / 'real-time.log'
    metrics = RealtimeMetrics()

    # Load previous state if savestate_file is provided
    if savestate_file:
        savestate_path = Path(savestate_file)
        if savestate_path.exists():
            print(f"Loading previous state from {savestate_path}")
            metrics.load_state(savestate_path)

    # Start Prometheus HTTP server
    start_http_server(port)
    print(f"Starting Prometheus exporter v{RealtimeMetrics.VERSION} on port {port}")
    print(f"Monitoring log file: {log_path}")

    while True:
        try:
            if not log_path.exists():
                print(f"Log file not found: {log_path}")
            else:
                logs = read_log(log_path)
                new_logs = [log for log in logs if parse_time(log['time']) > metrics.last_time]

                if new_logs:
                    metrics.last_time = max(parse_time(log['time']) for log in new_logs)
                    for log in new_logs:
                        metrics.process_log(log)

                # Save state if savestate_file is provided
                if savestate_file:
                    metrics.save_state(savestate_file)

        except Exception as e:
            print(f"Error processing logs: {e}")

        time.sleep(polling_time)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Prometheus exporter for realtime metrics')
    parser.add_argument('--logs-path', default='data/logs',
                      help='Path to the directory containing log files')
    parser.add_argument('--polling-time', type=int, default=60,
                      help='Time in seconds between log checks')
    parser.add_argument('--savestate-file', 
                      help='Path to file for saving/loading state (optional)')

    args = parser.parse_args()
    main(logs_path=args.logs_path, 
         polling_time=args.polling_time,
         savestate_file=args.savestate_file)
