# Cloudflare Prometheus Exporter

A modern Prometheus exporter for Cloudflare analytics and zone metrics for free plans.

## Features

- 📊 Zone analytics (requests, bandwidth, threats)
- 🔒 Secure API token authentication
- 🐳 Docker support with multi-architecture builds
- 📈 Prometheus-compatible metrics endpoint
- ⚡ Low resource usage
- 🔄 Automatic metric collection

## Metrics Exported

- `cloudflare_zone_info` - Zone information (name, status, plan)
- `cloudflare_zone_requests_total` - Total requests
- `cloudflare_zone_requests_cached` - Cached requests
- `cloudflare_zone_requests_uncached` - Uncached requests
- `cloudflare_zone_bandwidth_total_bytes` - Total bandwidth
- `cloudflare_zone_bandwidth_cached_bytes` - Cached bandwidth
- `cloudflare_zone_bandwidth_uncached_bytes` - Uncached bandwidth
- `cloudflare_zone_threats_total` - Threats blocked
- `cloudflare_zone_pageviews_total` - Page views
- `cloudflare_zone_uniques_total` - Unique visitors

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Cloudflare API Token with Analytics:Read permissions

### Create API Token

1. Go to Cloudflare Dashboard → Profile → API Tokens
2. Click "Create Token"
3. Use "Read Analytics" template or create custom token with:
   - Permissions: `Zone → Analytics → Read`
   - Zone Resources: Include zones you want to collect metrics from
4. Copy the generated token

### Running with Docker Compose

1. Create `.env` file:

```bash
CF_API_TOKEN=your_token_here
CLOUDFLARE_ZONES=example.com,another.com  # Optional: filter specific zones
```

2. Start the exporter:

```bash
docker-compose up -d cloudflare-exporter
```

3. View metrics:

```bash
curl http://localhost:9199/metrics
```

### Running with Docker

```bash
docker run -d \
  -p 9199:9199 \
  -e CF_API_TOKEN=your_token_here \
  johanneszelger/cloudflare-exporter:latest
```

### Running Locally

```bash
pip install -r requirements.txt
export CF_API_TOKEN=your_token_here
python exporter.py
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CF_API_TOKEN` | Yes | - | Cloudflare API token |
| `CLOUDFLARE_ZONES` | No | All zones | Comma-separated list of zones to monitor |
| `EXPORTER_PORT` | No | 9199 | Port for metrics endpoint |
| `LOG_LEVEL` | No | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Prometheus Configuration

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'cloudflare'
    static_configs:
      - targets: ['cloudflare-exporter:9199']
    scrape_interval: 60s
```

### Grafana Dashboard

Example PromQL queries:

```promql
# Request rate
rate(cloudflare_zone_requests_total[5m])

# Cache hit ratio
cloudflare_zone_requests_cached / cloudflare_zone_requests_total

# Bandwidth usage
rate(cloudflare_zone_bandwidth_total_bytes[5m])

# Threat rate
rate(cloudflare_zone_threats_total[5m])
```

## Troubleshooting

### Check exporter logs

```bash
docker logs cloudflare-exporter
```

### Verify API token

```bash
curl -X GET "https://api.cloudflare.com/client/v4/user/tokens/verify" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json"
```

### Test metrics endpoint

```bash
curl http://localhost:9199/metrics
```

## Contributing

Contributions welcome! Please open an issue or submit a pull request.

## License

MIT License - feel free to use and modify as needed.

## Support

For issues or questions:
- Open a GitHub issue
- Check Cloudflare API documentation
- Review exporter logs for errors
