"""
Business logic services for Salary Service
"""

from .geocoding import (
    geocode_address,
    geocode_address_yandex,
    geocode_address_nominatim,
    get_distance_osrm,
    is_moscow_region,
    calculate_fuel_cost,
)

from .calculation import (
    calculate_row,
    generate_alarms,
)

from .excel_parser import (
    parse_excel_file,
    parse_both_excel_files,
)

from .excel_report import (
    create_excel_report,
    create_worker_report,
)

__all__ = [
    # Geocoding
    'geocode_address',
    'geocode_address_yandex',
    'geocode_address_nominatim',
    'get_distance_osrm',
    'is_moscow_region',
    'calculate_fuel_cost',
    # Calculation
    'calculate_row',
    'generate_alarms',
    # Excel parser
    'parse_excel_file',
    'parse_both_excel_files',
    # Excel report
    'create_excel_report',
    'create_worker_report',
]
