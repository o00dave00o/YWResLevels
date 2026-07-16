import json
import os
import pandas as pd
import requests


def fetch_reservoir_data():
    """Fetches Yorkshire Water 2026 reservoir levels from the Stream Portal (ArcGIS FeatureServer)"""
    # Using the live 2026 European server URL!
    query_url = (
        "https://services-eu1.arcgis.com/1WqkK5cDKUbF0CkH/arcgis/rest/services/"
        "Yorkshire%20Water%20Reservoir%20Levels%202026/FeatureServer/0/query"
    )

    params = {
        "where": "1=1",
        "outFields": "RESERVOIR_NAME,DATE,CAPACITY,CURRENT_LEVEL,CURRENT_PERCENTAGE,LATITUDE,LONGITUDE",
        "f": "json",
        "resultOffset": 0,
        "resultRecordCount": 2000,
    }

    all_features = []
    print("-> Connecting to Stream Open Data Portal (2026 Live Feed)...")

    try:
        while True:
            response = requests.get(query_url, params=params, timeout=15)
            if response.status_code != 200:
                print(f"-> API Error: Received HTTP status code {response.status_code}")
                break

            data = response.json()
            
            if "error" in data:
                raise ValueError(f"ArcGIS Server Error: {data['error'].get('message')}")

            features = data.get("features", [])
            if not features:
                break

            all_features.extend(features)
            if len(features) < params["resultRecordCount"]:
                break
            params["resultOffset"] += len(features)

        if not all_features:
            raise ValueError("No data returned from the API server.")

        print(f"-> Successfully downloaded {len(all_features)} live records!")
        
        # Convert Esri attributes to a DataFrame
        df = pd.DataFrame([f["attributes"] for f in all_features])
        df.columns = [col.lower() for col in df.columns]
        
        if 'date' not in df.columns:
            raise ValueError("Expected column 'DATE' was not found in API response.")

        df["date"] = pd.to_datetime(df["date"], unit="ms")
        return df

    except Exception as api_err:
        print(f"-> API/Data processing failed: {api_err}")
        print("-> Falling back to generating the dashboard with MOCK DATA!")
        return get_fallback_mock_data()


def get_fallback_mock_data():
    """Generates mock data (with coordinate pins) in case the Yorkshire Water API is unreachable."""
    mock_records = [
        {"reservoir_name": "GRIMWITH IRE", "date": "2026-01-15", "capacity": 21764, "current_level": 21328, "current_percentage": 98.0, "latitude": 54.076, "longitude": -1.910},
        {"reservoir_name": "GRIMWITH IRE", "date": "2026-02-15", "capacity": 21764, "current_level": 21111, "current_percentage": 97.0, "latitude": 54.076, "longitude": -1.910},
        {"reservoir_name": "ECCUP ESR", "date": "2026-01-15", "capacity": 7009, "current_level": 6167, "current_percentage": 88.0, "latitude": 53.871, "longitude": -1.533},
        {"reservoir_name": "ECCUP ESR", "date": "2026-02-15", "capacity": 7009, "current_level": 6097, "current_percentage": 87.0, "latitude": 53.871, "longitude": -1.533},
    ]
    df = pd.DataFrame(mock_records)
    df["date"] = pd.to_datetime(df["date"])
    return df


def generate_interactive_html(df, output_filename="index.html"):
    """Aggregates data by month and writes a responsive interactive HTML dashboard."""
    print("-> Processing and aggregating data...")

    # Create helper columns for monthly grouping
    df["year_month"] = df["date"].dt.strftime("%Y-%m")
    df["month_name"] = df["date"].dt.strftime("%b %Y")

    # Group by reservoir and month to get average levels
    monthly_grouped = (
        df.groupby(["reservoir_name", "year_month", "month_name"])
        .agg(
            {
                "current_level": "mean",
                "current_percentage": "mean",
                "capacity": "max",
            }
        )
        .reset_index()
        .sort_values(by=["reservoir_name", "year_month"])
    )

    # Format values for neat presentation
    monthly_grouped["current_level"] = monthly_grouped["current_level"].round(2)
    monthly_grouped["current_percentage"] = monthly_grouped["current_percentage"].round(1)

    # Build a nested dictionary of reservoirs -> monthly lists of data
    reservoir_data_dict = {}
    for res_name, group in monthly_grouped.groupby("reservoir_name"):
        reservoir_data_dict[res_name] = {
            "capacity": int(group["capacity"].iloc[0]),
            "months": group["month_name"].tolist(),
            "percentages": group["current_percentage"].tolist(),
            "levels": group["current_level"].tolist(),
        }

    # Serialize dataset to JSON
    json_data = json.dumps(reservoir_data_dict, indent=2)

    # --- CALCULATE NETWORK SUMMARY METRICS (LATEST MONTH) ---
    # Grab the absolute latest record for each unique reservoir to represent current status
    latest_records_idx = df.groupby('reservoir_name')['date'].idxmax()
    latest_df = df.loc[latest_records_idx].copy()
    
    # Calculate volumetric totals
    latest_df['current_volume'] = latest_df['capacity'] * (latest_df['current_percentage'] / 100.0)
    
    total_max_capacity = latest_df['capacity'].sum()
    total_current_reserves = latest_df['current_volume'].sum()
    
    if total_max_capacity > 0:
        total_percentage = (total_current_reserves / total_max_capacity) * 100.0
    else:
        total_percentage = 0.0

    # Format metrics for HTML template
    str_total_max = f"{total_max_capacity:,.0f}"
    str_total_reserves = f"{total_current_reserves:,.0f}"
    str_total_percentage = f"{total_percentage:.1f}"

    # --- BUILD THE SORTED MASTER DIRECTORY ROWS ---
    master_list_df = latest_df.sort_values(by="capacity", ascending=False)
    table_rows_html = ""
    for _, row in master_list_df.iterrows():
        res_name = row['reservoir_name']
        cap = int(row['capacity'])
        pct = round(row['current_percentage'], 1) if pd.notnull(row['current_percentage']) else 'N/A'
        lat = row.get('latitude')
        lng = row.get('longitude')
        
        if pd.notnull(lat) and pd.notnull(lng):
            maps_link = f'<a href="https://www.google.com/maps/search/?api=1&query={lat},{lng}" target="_blank" class="text-blue-600 hover:text-blue-800 hover:underline inline-flex items-center gap-1 font-semibold">📍 View Map</a>'
        else:
            maps_link = '<span class="text-slate-400 italic">No coordinates</span>'
            
        table_rows_html += f"""
        <tr class="hover:bg-slate-50 border-b border-slate-100 transition">
            <td class="py-3.5 px-4 font-bold text-slate-900">{res_name}</td>
            <td class="py-3.5 px-4 text-right text-slate-700 font-mono">{cap:,.0f} m³</td>
            <td class="py-3.5 px-4 text-right">
                <span class="inline-block px-2.5 py-1 text-xs font-bold rounded-full {'bg-red-50 text-red-700' if pct != 'N/A' and pct < 50 else 'bg-blue-50 text-blue-700'}">
                    {pct}%
                </span>
            </td>
            <td class="py-3.5 px-4 text-center">{maps_link}</td>
        </tr>
        """

    # HTML template with Summary Cards placeholder
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Yorkshire Water Reservoir Monthly Levels</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen font-sans">

    <div class="max-w-6xl mx-auto px-4 py-8">
        <!-- Header -->
        <header class="mb-8 border-b border-slate-200 pb-5">
            <h1 class="text-3xl font-extrabold text-slate-900 tracking-tight">Yorkshire Water Reservoir Levels Dashboard</h1>
            <p class="text-slate-500 mt-2">Active monthly monitoring compiled via Stream Open Data Portal.</p>
        </header>

        <!-- Network-Wide Summary KPI Cards -->
        <section class="grid grid-cols-1 md:grid-cols-3 gap-5 mb-8">
            <!-- Card 1: Total Max Capacity -->
            <div class="bg-gradient-to-tr from-slate-900 to-slate-800 text-white p-6 rounded-2xl shadow-md">
                <span class="block text-xs uppercase tracking-wider font-bold text-slate-400">Total Network Capacity</span>
                <div class="mt-2 flex items-baseline gap-2">
                    <span class="text-3xl font-extrabold">__METRIC_MAX_CAP__</span>
                    <span class="text-sm font-semibold text-slate-300">m³</span>
                </div>
                <p class="text-slate-400 text-xs mt-2">Combined maximum capacity of all monitored reservoirs.</p>
            </div>

            <!-- Card 2: Current Active Reserves -->
            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                <span class="block text-xs uppercase tracking-wider font-semibold text-slate-500">Current Total Reserves</span>
                <div class="mt-2 flex items-baseline gap-2">
                    <span class="text-3xl font-extrabold text-slate-900">__METRIC_CUR_VOL__</span>
                    <span class="text-sm font-semibold text-slate-500">m³</span>
                </div>
                <p class="text-slate-400 text-xs mt-2">Estimated current storage volume based on latest readings.</p>
            </div>

            <!-- Card 3: Combined Percentage -->
            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                <span class="block text-xs uppercase tracking-wider font-semibold text-slate-500">Overall Reserve Level</span>
                <div class="mt-2 flex items-baseline gap-2">
                    <span class="text-3xl font-extrabold text-blue-600">__METRIC_TOTAL_PCT__%</span>
                </div>
                <!-- Mini Progress Bar -->
                <div class="w-full bg-slate-100 rounded-full h-2.5 mt-3">
                    <div class="bg-blue-600 h-2.5 rounded-full" style="width: __METRIC_TOTAL_PCT__%"></div>
                </div>
            </div>
        </section>

        <!-- Dynamic Selector Panel -->
        <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
                <label for="res-selector" class="block text-sm font-semibold text-slate-600 mb-1">Select an Individual Reservoir</label>
                <select id="res-selector" class="w-full sm:w-72 bg-slate-50 border border-slate-200 text-slate-800 py-2.5 px-4 rounded-xl focus:ring-2 focus:ring-blue-500 focus:outline-none font-medium cursor-pointer transition font-bold">
                </select>
            </div>
            <div class="flex gap-6">
                <div>
                    <span class="block text-xs uppercase tracking-wider font-bold text-slate-400">Total Capacity</span>
                    <span id="capacity-val" class="text-2xl font-bold text-slate-900">-</span> <span class="text-xs text-slate-500 font-semibold">m³</span>
                </div>
                <div>
                    <span class="block text-xs uppercase tracking-wider font-bold text-slate-400">Current Average</span>
                    <span id="latest-pct" class="text-2xl font-bold text-blue-600">-</span>
                </div>
            </div>
        </div>

        <!-- Dashboard Grid -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-12">
            <div class="lg:col-span-2 bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                <h3 class="text-lg font-bold text-slate-900 mb-4">Historical Storage Trend (%)</h3>
                <div class="relative h-96 w-full">
                    <canvas id="reservoirChart"></canvas>
                </div>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 flex flex-col h-full">
                <h3 class="text-lg font-bold text-slate-900 mb-4">Monthly Breakdown</h3>
                <div class="overflow-y-auto flex-1 pr-1 max-h-96">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-slate-100 text-xs font-bold text-slate-400 uppercase">
                                <th class="pb-3">Month</th>
                                <th class="pb-3 text-right">Avg Level (m)</th>
                                <th class="pb-3 text-right">Capacity %</th>
                            </tr>
                        </thead>
                        <tbody id="table-body" class="text-sm font-medium text-slate-600 divide-y divide-slate-50">
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Master Directory -->
        <div class="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
            <div class="px-6 py-5 border-b border-slate-100 bg-slate-50/50">
                <h2 class="text-xl font-bold text-slate-900">Yorkshire Water Reservoir Directory</h2>
                <p class="text-slate-500 text-sm mt-0.5">Comprehensive list of managed reservoirs ordered by largest holding capacity.</p>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-slate-50 text-slate-500 text-xs font-bold uppercase tracking-wider border-b border-slate-200">
                            <th class="py-4 px-4">Reservoir Name</th>
                            <th class="py-4 px-4 text-right">Max Capacity</th>
                            <th class="py-4 px-4 text-right">Current Level %</th>
                            <th class="py-4 px-4 text-center">Location Link</th>
                        </tr>
                    </thead>
                    <tbody class="text-sm font-medium divide-y divide-slate-100">
                        __MASTER_TABLE_ROWS__
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        const reservoirData = __RESERVOIR_JSON_DATA__;
        let chartInstance = null;

        const selector = document.getElementById('res-selector');
        const capacityVal = document.getElementById('capacity-val');
        const latestPct = document.getElementById('latest-pct');
        const tableBody = document.getElementById('table-body');
        const ctx = document.getElementById('reservoirChart').getContext('2d');

        const sortedReservoirs = Object.keys(reservoirData).sort();
        sortedReservoirs.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            selector.appendChild(opt);
        });

        function updateDashboard(resName) {
            const data = reservoirData[resName];
            capacityVal.textContent = Number(data.capacity).toLocaleString();
            
            const lastPercentage = data.percentages[data.percentages.length - 1];
            latestPct.textContent = lastPercentage ? lastPercentage + '%' : 'N/A';

            if (chartInstance) {
                chartInstance.destroy();
            }

            chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: data.months,
                    datasets: [{
                        label: 'Water Capacity %',
                        data: data.percentages,
                        borderColor: '#2563eb',
                        backgroundColor: 'rgba(37, 99, 235, 0.08)',
                        fill: true,
                        tension: 0.35,
                        borderWidth: 3,
                        pointRadius: 4,
                        pointHoverRadius: 7,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            padding: 12,
                            backgroundColor: '#1e293b',
                            titleFont: { size: 14, weight: 'bold' },
                            bodyFont: { size: 13 }
                        }
                    },
                    scales: {
                        y: {
                            min: 0,
                            max: 100,
                            ticks: { callback: value => value + '%' },
                            grid: { color: '#f1f5f9' }
                        },
                        x: {
                            grid: { display: false }
                        }
                    }
                }
            });

            tableBody.innerHTML = '';
            for (let i = data.months.length - 1; i >= 0; i--) {
                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-50 transition-colors';
                tr.innerHTML = `
                    <td class="py-3 font-semibold text-slate-800">${data.months[i]}</td>
                    <td class="py-3 text-right text-slate-500">${data.levels[i] !== null ? data.levels[i] + 'm' : 'N/A'}</td>
                    <td class="py-3 text-right font-bold text-blue-600">${data.percentages[i]}%</td>
                `;
                tableBody.appendChild(tr);
            }
        }

        selector.addEventListener('change', (e) => updateDashboard(e.target.value));

        if(sortedReservoirs.length > 0) {
            updateDashboard(sortedReservoirs[0]);
        }
    </script>
</body>
</html>
"""

    # Inject variables clean and fast using .replace()
    final_html = html_content.replace("__RESERVOIR_JSON_DATA__", json_data)
    final_html = final_html.replace("__MASTER_TABLE_ROWS__", table_rows_html)
    
    # Inject new network KPI metrics
    final_html = final_html.replace("__METRIC_MAX_CAP__", str_total_max)
    final_html = final_html.replace("__METRIC_CUR_VOL__", str_total_reserves)
    final_html = final_html.replace("__METRIC_TOTAL_PCT__", str_total_percentage)

    # Output path resolution
    script_dir = os.path.dirname(os.path.abspath(__file__))
    full_output_path = os.path.join(script_dir, output_filename)

    with open(full_output_path, "w", encoding="utf-8") as f:
        f.write(final_html)

    print(f"\n-> SUCCESS!")
    print(f"-> Interactive dashboard saved to: {full_output_path}")


if __name__ == "__main__":
    try:
        raw_df = fetch_reservoir_data()
        generate_interactive_html(raw_df)
    except Exception as e:
        print(f"\n-> CRITICAL ERROR: {e}")