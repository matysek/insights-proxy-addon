"""This script is used to scale the Insights Proxy deployment on the hub cluster.

It will:
1. Accept the Proxy URL as a command line argument (or none)
2. Load the archive given as a command line argument
3. Send X request concurrently to the Proxy URL (or console.redhat.com if no Proxy URL is provided)
  a. if request-type argument is "GET", a request to the /api/insights-results-aggregator/v2/cluster/<cluster_id>/reports endpoint is sent
  b. if request-type argument is "POST", a request to the /api/ingress/v1/upload endpoint is sent
4. Measure the time it takes to send the requests
"""

from dotenv import load_dotenv
import os
import requests
import time
import statistics
import matplotlib.pyplot as plt
from tqdm import tqdm

load_dotenv()

CLIENT_ID = os.environ.get('CLIENT_ID')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
CLUSTER_ID = "d4efb5bf-4156-4b52-9599-0443add543d5"
IO_PATH = "io-archive.tar.gz"
IO_COMMIT_HASH = "b414946202b350698cb388b5aa32260716735d84"
CONTENT_TYPE = "application/vnd.redhat.openshift.periodic+tar"
TIME_BETWEEN_TESTS = 30

PROXIES = {
    "http": "http://a7329a76ff0ba441683d8558a6fce358-1215085193.us-east-1.elb.amazonaws.com:80",
    "https": "http://a7329a76ff0ba441683d8558a6fce358-1215085193.us-east-1.elb.amazonaws.com:80",
}


def get_access_token():
    token_url = "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token"
    data = {
        "grant_type": "client_credentials"
    }

    response = requests.post(
        token_url,
        data=data,
        auth=(CLIENT_ID, CLIENT_SECRET)
    )

    response.raise_for_status()
    return response.json().get("access_token")

def time_get_request(access_token, url, method, data=None, proxies=None) -> float:
    start_time = time.time()
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    response = requests.request(method, url, headers=headers, data=data, proxies=proxies)
    assert response.status_code in [200, 404], f"Expected 200 or 404, got {response.status_code}: {response.text}"
    return time.time() - start_time


def time_post_request(access_token, url, proxies=None) -> float:
    start_time = time.time()

    headers = {
        'accept': 'application/json',
        'Authorization': f"Bearer {access_token}",
        'User-Agent': f"cluster/{CLUSTER_ID}",
    }

    print(headers)

    files = {
        'file': (IO_PATH, open(IO_PATH, 'rb'), CONTENT_TYPE),
        'metadata': (None, ''),
    }

    response = requests.post(url, headers=headers, files=files, timeout=10, proxies=proxies)
    response.raise_for_status()
    return time.time() - start_time


def calculate_performance_metrics(access_token: str, cluster_sizes: list[int], proxies=None) -> dict:
    """Calculate performance metrics for GET and POST requests across different cluster sizes."""
    result = {
        "n_clusters": [],
        "get_average": [],
        "get_min": [],
        "get_max": [],
        "get_std": [],
        "post_average": [],
        "post_min": [],
        "post_max": [],
        "post_std": [],
    }
    
    for n_clusters in tqdm(cluster_sizes, desc="Cluster sizes"):
        get_times = []
        post_times = []
        for _ in tqdm(range(n_clusters), desc=f"Testing {n_clusters} clusters", leave=False):
            get_times.append(time_get_request(access_token, f"https://console.redhat.com/api/insights-results-aggregator/v2/cluster/{CLUSTER_ID}/reports?get_disabled=false", "GET", proxies=proxies))
            post_times.append(time_post_request(access_token, "https://console.redhat.com/api/ingress/v1/upload", proxies=proxies))
        
        result["n_clusters"].append(n_clusters)
        result["get_average"].append(sum(get_times) / len(get_times))
        result["get_min"].append(min(get_times))
        result["get_max"].append(max(get_times))
        result["get_std"].append(statistics.stdev(get_times))
        result["post_average"].append(sum(post_times) / len(post_times))
        result["post_min"].append(min(post_times))
        result["post_max"].append(max(post_times))
        result["post_std"].append(statistics.stdev(post_times))

        time.sleep(TIME_BETWEEN_TESTS)  # give the API some time to recover
    
    return result


def plot_results(result: dict):
    """Plot GET and POST request performance metrics."""
    print("\nResults:")
    print(result)
    
    # Create figure with 2 subplots
    _, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Plot GET requests
    ax1.plot(result["n_clusters"], result["get_average"], 'o-', label='Average', linewidth=2, markersize=8)
    ax1.fill_between(result["n_clusters"], result["get_min"], result["get_max"], alpha=0.2, label='Min-Max Range')
    ax1.errorbar(result["n_clusters"], result["get_average"], yerr=result["get_std"], 
                 fmt='none', capsize=5, capthick=2, ecolor='red', alpha=0.5, label='Std Dev')
    ax1.set_xlabel('Number of Clusters', fontsize=12)
    ax1.set_ylabel('Time (seconds)', fontsize=12)
    ax1.set_title('GET Request Performance', fontsize=14, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_xscale('log')
    
    # Plot POST requests
    ax2.plot(result["n_clusters"], result["post_average"], 'o-', label='Average', linewidth=2, markersize=8, color='orange')
    ax2.fill_between(result["n_clusters"], result["post_min"], result["post_max"], alpha=0.2, label='Min-Max Range', color='orange')
    ax2.errorbar(result["n_clusters"], result["post_average"], yerr=result["post_std"], 
                 fmt='none', capsize=5, capthick=2, ecolor='red', alpha=0.5, label='Std Dev')
    ax2.set_xlabel('Number of Clusters', fontsize=12)
    ax2.set_ylabel('Time (seconds)', fontsize=12)
    ax2.set_title('POST Request Performance', fontsize=14, fontweight='bold')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_xscale('log')
    
    plt.tight_layout()
    plt.savefig('scale_results.png', dpi=300, bbox_inches='tight')
    print("\nPlot saved as 'scale_results.png'")
    plt.show()

if __name__ == "__main__":
    access_token = get_access_token()
    took = time_get_request(access_token, f"https://console.redhat.com/api/insights-results-aggregator/v2/cluster/{CLUSTER_ID}/reports?get_disabled=false", "GET")
    print(f"GET total time: {took} seconds")
    took = time_post_request(access_token, "https://console.redhat.com/api/ingress/v1/upload")
    print(f"POST total time: {took} seconds")

    print("With Insights Proxy:")
    took = time_get_request(access_token, f"https://console.redhat.com/api/insights-results-aggregator/v2/cluster/{CLUSTER_ID}/reports?get_disabled=false", "GET", proxies=PROXIES)
    print(f"GET total time: {took} seconds")
    took = time_post_request(access_token, "https://console.redhat.com/api/ingress/v1/upload", proxies=PROXIES)
    print(f"POST total time: {took} seconds")

    # result = calculate_performance_metrics(access_token, [10, 50, 100])#, 1000])
    # plot_results(result)
