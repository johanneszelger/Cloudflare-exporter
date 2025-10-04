"""
Cloudflare Prometheus Exporter
Exports Cloudflare Analytics metrics using GraphQL API to Prometheus
"""
import os
import time
import logging
from datetime import datetime, timedelta, timezone
from pydoc import browse

import requests
import sentry_sdk
from prometheus_client import start_http_server, REGISTRY
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily

from state import State

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if os.environ.get("SENTRY_DSN") :
    sentry_sdk.init(
        dsn=os.environ.get("SENTRY_DSN"),
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
        send_default_pii=True,
    )

class CloudflareCollector:
    def __init__(self, api_token, zones=None):
        self.api_token = api_token
        self.zones = zones or []
        self.graphql_url = "https://api.cloudflare.com/client/v4/graphql"
        self.rest_url = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        self._zone_cache = None
        self._zone_cache_time = 0
        self._zone_cache_ttl = 3600  # Cache zones for 1h

        self._state = State()

    def _make_rest_request(self, endpoint):
        """Make REST API request to Cloudflare"""
        try:
            url = f"{self.rest_url}/{endpoint}"
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data.get('success'):
                errors = data.get('errors', [])
                logger.error(f"API error: {errors}")
                return None

            return data.get('result')
        except Exception as e:
            logger.error(f"Request failed for {endpoint}: {e}")
            return None

    def _make_graphql_request(self, query):
        """Make GraphQL API request to Cloudflare"""
        try:
            response = requests.post(
                self.graphql_url,
                headers=self.headers,
                json={"query": query},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if data['errors'] is not None:
                logger.error(f"GraphQL errors: {data['errors']}")
                return None

            return data.get('data').get('viewer').get('zones')[0]
        except Exception as e:
            logger.error(f"GraphQL request failed: {e}")
            return None

    def get_zones(self):
        """Get all zones or filter by specified zones (with caching)"""
        current_time = time.time()

        # Return cached zones if still valid
        if self._zone_cache and (current_time - self._zone_cache_time) < self._zone_cache_ttl:
            return self._zone_cache

        result = self._make_rest_request("zones")
        if not result:
            return []

        zones = result
        if self.zones:
            zones = [z for z in zones if z['name'] in self.zones or z['id'] in self.zones]

        # Update cache
        self._zone_cache = zones
        self._zone_cache_time = current_time

        return zones

    def get_zone_analytics_graphql(self, zone_tag):
        """Get analytics for a zone using GraphQL"""
        # Calculate time range
        # Ensure we cover up to current hour
        end_time = datetime.now(timezone.utc) + timedelta(hours=1)
        # take last few hours, we get only the latest two anyways. We need the previous one as its data can still be updated for some time after the full hour
        start_time = datetime.now(timezone.utc) - timedelta(hours=3)

        # Format times for GraphQL (ISO 8601)
        start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # GraphQL query for httpRequests1hGroups
        query = f"""
        {{
          viewer {{
            zones(filter: {{zoneTag: "{zone_tag}"}}) {{
              httpRequests1hGroups(
                filter: {{
                  datetime_geq: "{start_str}"
                  datetime_leq: "{end_str}"
                }}
                limit: 2
                orderBy: [datetime_DESC]
              ) {{
                dimensions{{
                    datetime
                }}
                sum {{
                  requests
                  cachedRequests
                  bytes
                  cachedBytes
                  threats
                  pageViews
                    browserMap {{
                        pageViews
                        key: uaBrowserFamily
                    }}
                    contentTypeMap {{
                        bytes
                        requests
                        key: edgeResponseContentTypeName
                    }}
                    clientSSLMap {{
                        requests
                        key: clientSSLProtocol
                    }}
                    countryMap {{
                        bytes
                        requests
                        threats
                        key: clientCountryName
                    }}
                    ipClassMap {{
                        requests
                        key: ipType
                    }}
                    responseStatusMap {{
                        requests
                        key: edgeResponseStatus
                    }}
                    threatPathingMap {{
                        requests
                        key: threatPathingName
                    }}
                }}
                uniq {{
                  uniques
                }}
              }}
            }}
          }}
        }}
        """

        result = self._make_graphql_request(query)

        groups = result.get('httpRequests1hGroups', [])

        if not groups:
            logger.warning(f"No data returned for zone {zone_tag}")
        elif len(groups) < 2:
            logger.warning(f"Less than 2 data points returned for zone {zone_tag}, data may be incomplete")
            self._state.update(f"httpRequests1hGroupsSums_{zone_tag}", groups[0].get("sum", {}))
        else:
            self._state.update(f"httpRequests1hGroupsSums_{zone_tag}", groups[0].get("sum", {}),
                               groups[1].get("sum", {}))

        ret = {
            'requests': self.get_count_from_state(f"httpRequests1hGroupsSums_{zone_tag}", "requests"),
            'cachedRequests': self.get_count_from_state(f"httpRequests1hGroupsSums_{zone_tag}", "cachedRequests"),
            'bytes': self.get_count_from_state(f"httpRequests1hGroupsSums_{zone_tag}", "bytes"),
            'cachedBytes': self.get_count_from_state(f"httpRequests1hGroupsSums_{zone_tag}", "cachedBytes"),
            'threats': self.get_count_from_state(f"httpRequests1hGroupsSums_{zone_tag}", "threats"),
            'pageViews': self.get_count_from_state(f"httpRequests1hGroupsSums_{zone_tag}", "pageViews"),
            'uniques': self.get_count_from_state(f"httpRequests1hGroupsSums_{zone_tag}", "uniques"),
            'browsers': self.get_map_count_from_state(f"httpRequests1hGroupsSums_{zone_tag}", "browserMap_pageViews", "browsers"),
            'status': self.get_map_count_from_state(f"httpRequests1hGroupsSums_{zone_tag}", "responseStatusMap_requests", "status"),
            'countries': self.get_map_count_from_state(f"httpRequests1hGroupsSums_{zone_tag}", "countryMap_requests", "countries"),
        }

        return ret

    def get_firewall_events(self, zone_tag):
        """Get analytics for a zone using GraphQL"""
        # Calculate time range
        # Ensure we cover up to current hour
        end_time = datetime.now(timezone.utc) + timedelta(hours=1)
        # take last few hours, we get only the latest two anyways. We need the previous one as its data can still be updated for some time after the full hour
        start_time = datetime.now(timezone.utc) - timedelta(hours=3)

        # Format times for GraphQL (ISO 8601)
        start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # GraphQL query for httpRequests1hGroups
        query = f"""
       {{
          viewer {{
            zones(filter: {{zoneTag: "{zone_tag}"}}) {{
              firewallEventsAdaptive(
                filter: {{
                  datetime_geq: "{start_str}"
                  datetime_leq: "{end_str}"
                }}
                limit: 2
                orderBy: [datetime_DESC]
              ) {{
              action
              clientAsn
              clientCountryName
              clientIP
              clientRequestPath
              clientRequestQuery
              datetime
              source
              userAgent
              }}
            }}
          }}
        }}
        """

        result = self._make_graphql_request(query)

        groups = result.get('httpRequests1hGroups', [])

    def get_turnstile_graphql(self, zone_tag):
        """Get analytics for a zone using GraphQL"""
        # Always get since last crawl
        start_str = self._state.get_time("turnstile_last_crawl")
        end_time = datetime.now(timezone.utc)
        end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        if start_str is None:
            self._state.update_time(f"turnstile_last_crawl", end_str)
            return {
                "issued": 0,
                "solved": 0
            }

        start_time = datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%SZ")
        #set time zone
        start_time = start_time.replace(tzinfo=timezone.utc)
        seconds_diff = (end_time - start_time).total_seconds()
        if seconds_diff < 60:
            # less than 1 minute since last crawl, skip
            logger.info(f"Skipping turnstile crawl for {zone_tag}, only {seconds_diff} seconds since last crawl")
            return self._state.get_cache("turnstile_last_crawl", {
                "issued": 0,
                "solved": 0
            })

        # GraphQL query for httpRequests1hGroups
        query = f"""
       {{
          viewer {{
            zones(filter: {{zoneTag: "{zone_tag}"}}) {{
              issued: firewallEventsAdaptiveByTimeGroups(
                filter: {{
                  datetime_geq: "{start_str}"
                  datetime_leq: "{end_str}"
                  OR: [
                    {{ action: "jschallenge" }}
                    {{ action: "managed_challenge" }}
                    {{ action: "challenge" }}
                  ]
                }}
                limit: 1
              ) {{
                count
              }}
              solved: firewallEventsAdaptiveByTimeGroups(
                limit: 1
                filter: {{
                  OR: [
                    {{ action: "jschallenge_solved" }}
                    {{ action: "challenge_solved" }}
                    {{ action: "managed_challenge_non_interactive_solved" }}
                    {{ action: "managed_challenge_interactive_solved" }}
                  ]
                  datetime_geq: "{start_str}"
                  datetime_leq: "{end_str}"
                }}
              ) {{
                count
              }}
            }}
          }}
        }}
        """

        result = self._make_graphql_request(query)

        self._state.update_time(f"turnstile_last_crawl", end_str)

        if result is None:
            return None

        res = {
            "issued": result['issued'][0] if len(result['issued']) else 0,
            "solved": result['solved'][0] if len(result['solved']) else 0
        }
        self._state.set_cache("turnstile_last_crawl", res)
        logging.debug(f"turnstile_last_crawl: {res}")
        return res


    def get_count_from_state(self, group_key, key):
        if group_key not in self._state.state or key not in self._state.state[group_key]:
            return 0
        return self._state.state[group_key][key]["counter"]

    def get_map_count_from_state(self, group_key, item_key, target_key):
        if f"{group_key}_{item_key}" not in self._state.state:
            return {}

        ret = {}
        for k in self._state.state[f"{group_key}_{item_key}"].keys():
            ret[k] = self.get_count_from_state(f"{group_key}_{item_key}", k)
        return ret

    def collect(self):
        logger.debug("Starting collection of metrics")

        """Collect metrics for Prometheus"""
        zones = self.get_zones()

        if not zones:
            logger.warning("No zones found")
            return

        logger.info(f"Collecting metrics for {len(zones)} zones")

        # Zone info
        zone_info = GaugeMetricFamily(
            'cloudflare_zone_info',
            'Cloudflare zone information',
            labels=['zone_id', 'zone_name', 'status', 'plan']
        )

        # Request metrics
        requests_total = CounterMetricFamily(
            'cloudflare_zone_requests_total',
            'Total requests to zone',
            labels=['zone_id', 'zone_name']
        )

        requests_cached = CounterMetricFamily(
            'cloudflare_zone_requests_cached',
            'Cached requests',
            labels=['zone_id', 'zone_name']
        )

        # Bandwidth metrics
        bandwidth_total = CounterMetricFamily(
            'cloudflare_zone_bandwidth_total_bytes',
            'Total bandwidth in bytes',
            labels=['zone_id', 'zone_name']
        )

        bandwidth_cached = CounterMetricFamily(
            'cloudflare_zone_bandwidth_cached_bytes',
            'Cached bandwidth in bytes',
            labels=['zone_id', 'zone_name']
        )

        # Threats
        threats_total = CounterMetricFamily(
            'cloudflare_zone_threats_total',
            'Total threats blocked',
            labels=['zone_id', 'zone_name']
        )

        # Page views
        pageviews_total = CounterMetricFamily(
            'cloudflare_zone_pageviews_total',
            'Total page views',
            labels=['zone_id', 'zone_name']
        )

        # Unique visitors
        uniques_total = CounterMetricFamily(
            'cloudflare_zone_uniques_total',
            'Total unique visitors',
            labels=['zone_id', 'zone_name']
        )

        # Browsers
        browsers_total = CounterMetricFamily(
            'cloudflare_zone_browsers',
            'Page views by browser',
            labels=['zone_id', 'zone_name', 'browser']
        )

        # Status codes
        status_total = CounterMetricFamily(
            'cloudflare_zone_response_status',
            'Repsponse status codes',
            labels=['zone_id', 'zone_name', 'status_code']
        )

        # Countries
        countries_total = CounterMetricFamily(
            'cloudflare_zone_countries',
            'Requests by country',
            labels=['zone_id', 'zone_name', 'country']
        )

        # turnstile solved
        turnstile_solved_total = GaugeMetricFamily(
            'cloudflare_zone_turnstile_solved',
            'Turnstile solved since last scrape',
            labels=['zone_id', 'zone_name']
        )
        # turnstile solved
        turnstile_issued_total = GaugeMetricFamily(
            'cloudflare_zone_turnstile_issued',
            'Turnstile issued since last scrape',
            labels=['zone_id', 'zone_name']
        )


        for zone in zones:
            zone_id = zone['id']
            zone_name = zone['name']
            status = zone['status']
            plan = zone['plan']['name']

            # Add zone info
            zone_info.add_metric([zone_id, zone_name, status, plan], 1)

            # Get analytics via GraphQL
            analytics = self.get_zone_analytics_graphql(zone_id)

            # turnstile
            turnstile = self.get_turnstile_graphql(zone_id)

            if analytics:
                # Requests
                req_all = analytics.get('requests', 0)
                req_cached = analytics.get('cachedRequests', 0)
                requests_total.add_metric([zone_id, zone_name], req_all)
                requests_cached.add_metric([zone_id, zone_name], req_cached)

                # Bandwidth
                bw_all = analytics.get('bytes', 0)
                bw_cached = analytics.get('cachedBytes', 0)
                bandwidth_total.add_metric([zone_id, zone_name], bw_all)
                bandwidth_cached.add_metric([zone_id, zone_name], bw_cached)

                # Threats
                threats = analytics.get('threats', 0)
                threats_total.add_metric([zone_id, zone_name], threats)

                # Page views
                pageviews = analytics.get('pageViews', 0)
                pageviews_total.add_metric([zone_id, zone_name], pageviews)

                # Uniques
                uniques = analytics.get('uniques', 0)
                uniques_total.add_metric([zone_id, zone_name], uniques)

                browsers = analytics.get('browsers', 0)
                for browser, count in browsers.items():
                    browsers_total.add_metric([zone_id, zone_name, browser], count)

                # Status codes
                status = analytics.get('status', 0)
                for status_code, count in status.items():
                    status_total.add_metric([zone_id, zone_name, str(status_code)], count)

                # Countries
                countries = analytics.get('countries', 0)
                for country, count in countries.items():
                    countries_total.add_metric([zone_id, zone_name, country], count)

            else:
                # Add zeros if no data available
                requests_total.add_metric([zone_id, zone_name], 0)

            if turnstile:
                a = turnstile.get("solved", 0.)
                b = turnstile.get("issued", 0.)
                if not isinstance(a, float) and not isinstance(a, int) and not isinstance(a, str):
                    a = 0.
                if not isinstance(b, float) and not isinstance(b, int) and not isinstance(b, str):
                    b = 0.
                turnstile_solved_total.add_metric([zone_id, zone_name], turnstile.get("solved", 0.))
                turnstile_issued_total.add_metric([zone_id, zone_name], turnstile.get("issued", 0.))
            else:
                turnstile_solved_total.add_metric([zone_id, zone_name], 0.)
                turnstile_issued_total.add_metric([zone_id, zone_name], 0.)

        yield zone_info
        yield requests_total
        yield requests_cached
        yield bandwidth_total
        yield bandwidth_cached
        yield threats_total
        yield pageviews_total
        yield uniques_total
        yield browsers_total
        yield status_total
        yield countries_total
        yield turnstile_solved_total
        yield turnstile_issued_total


def main():
    # Configuration from environment variables
    api_token = os.getenv('CF_API_TOKEN')
    if not api_token:
        logger.error("CF_API_TOKEN environment variable is required")
        return

    # Optional: filter specific zones
    zones_filter = os.getenv('CLOUDFLARE_ZONES', '').split(',')
    zones_filter = [z.strip() for z in zones_filter if z.strip()]

    # Exporter port
    port = int(os.getenv('EXPORTER_PORT', '9199'))

    # Register collector
    collector = CloudflareCollector(api_token, zones_filter)
    REGISTRY.register(collector)

    # Start HTTP server
    start_http_server(port)
    logger.info(f"Cloudflare exporter started on port {port}")
    logger.info(f"Metrics available at http://localhost:{port}/metrics")

    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Exporter stopped")


if __name__ == '__main__':
    main()
