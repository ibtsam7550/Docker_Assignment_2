"""Parser adapted from the uploaded httperf_load_test(2).py."""
import re


def number(text, pattern):
    match = re.search(pattern, text, re.MULTILINE)
    return float(match.group(1)) if match else None


def parse(text):
    patterns = {
        'requests': r'^Total: connections \d+ requests (\d+)',
        'replies': r'^Total: connections \d+ requests \d+ replies (\d+)',
        'duration_s': r'^Total:.*test-duration ([\d.]+)',
        'sent_req_s': r'^Request rate: ([\d.]+)',
        'response_ms': r'^Reply time \[ms\]: response ([\d.]+)',
        'transfer_ms': r'^Reply time \[ms\]:.*transfer ([\d.]+)',
        'connection_avg_ms': r'^Connection time \[ms\]: min [\d.]+ avg ([\d.]+)',
        'http_2xx': r'^Reply status:.*2xx=(\d+)',
        'http_3xx': r'^Reply status:.*3xx=(\d+)',
        'http_4xx': r'^Reply status:.*4xx=(\d+)',
        'http_5xx': r'^Reply status:.*5xx=(\d+)',
        'errors': r'^Errors: total (\d+)',
        'client_timeouts': r'^Errors:.*client-timo (\d+)',
        'socket_timeouts': r'^Errors:.*socket-timo (\d+)',
        'refused': r'^Errors:.*connrefused (\d+)',
        'reset': r'^Errors:.*connreset (\d+)',
        'fd_unavailable': r'^Errors:.*fd-unavail (\d+)',
        'address_unavailable': r'^Errors:.*addrunavail (\d+)',
        'file_table_full': r'^Errors:.*ftab-full (\d+)',
        'generator_cpu_pct': r'^CPU time.*total ([\d.]+)%',
    }
    values = {key: number(text, pat) for key, pat in patterns.items()}
    duration = values['duration_s']
    for name, numerator in [('replies_s', 'replies'), ('successful_req_s', 'http_2xx')]:
        values[name] = (round(values[numerator] / duration, 3)
                        if duration and values[numerator] is not None else None)
    return values

