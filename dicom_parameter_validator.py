#!/usr/bin/env python3
# dicom_parameter_validator.py (v4 - with index checking)

import argparse
import json
import os
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation

try:
    import pydicom
    from pydicom.errors import InvalidDicomError
except ImportError:
    print("Error: pydicom library not found. Please install it with 'pip install pydicom'")
    sys.exit(1)

def parse_tag(tag_str_or_keyword):
    """
    Parses a string that is either a pydicom keyword or a DICOM tag like '(gggg,eeee)'.
    Returns the keyword or a tuple of integers for the tag.
    """
    if isinstance(tag_str_or_keyword, str) and tag_str_or_keyword.startswith('('):
        try:
            parts = tag_str_or_keyword.strip('() ').split(',')
            if len(parts) != 2:
                raise ValueError("Tag must have two parts: group and element.")
            group = int(parts[0].strip(), 16)
            element = int(parts[1].strip(), 16)
            return (group, element)
        except (ValueError, IndexError) as e:
            print(f"  [CONFIG_ERROR] Invalid DICOM tag format: '{tag_str_or_keyword}'. Must be '(gggg,eeee)'. Error: {e}", file=sys.stderr)
            return None
    return tag_str_or_keyword

def load_config(config_path):
    """Loads the JSON configuration file."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        if "series_identifier_tag" not in config or "series_rules" not in config:
            raise ValueError("Configuration file must contain 'series_identifier_tag' and 'series_rules'.")
        return config
    except FileNotFoundError:
        print(f"Error: Configuration file not found at {config_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {config_path}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error in configuration file structure: {e}", file=sys.stderr)
        sys.exit(1)

def find_dicom_series(dicom_dir_path, series_identifier_config_val):
    """
    Scans the DICOM directory, groups files by series identifier.
    Returns a dictionary: {series_id_value: [list_of_dcm_paths]}
    """
    series_identifier_tag = parse_tag(series_identifier_config_val)
    if series_identifier_tag is None:
        print(f"Exiting due to invalid 'series_identifier_tag': '{series_identifier_config_val}' in config.", file=sys.stderr)
        sys.exit(1)

    series_map = defaultdict(list)
    print(f"\nScanning DICOM directory: {dicom_dir_path}")
    print(f"Identifying series using DICOM Tag: '{series_identifier_config_val}'")

    for root, _, files in os.walk(dicom_dir_path):
        for file in files:
            if file.lower().endswith(('.dcm', '.dicom')) or '.' not in file.lower():
                file_path = os.path.join(root, file)
                try:
                    # Reading only the specific tag is faster for series discovery
                    dcm = pydicom.dcmread(file_path, stop_before_pixels=True, specific_tags=[series_identifier_tag])
                    series_id_element = dcm.get(series_identifier_tag, None)
                    if series_id_element is not None:
                        series_map[str(series_id_element.value)].append(file_path)
                except InvalidDicomError:
                    pass
                except Exception:
                    # Fallback for when specific_tags fails (rare), read header
                    try:
                        dcm = pydicom.dcmread(file_path, stop_before_pixels=True)
                        series_id_element = dcm.get(series_identifier_tag, None)
                        if series_id_element is not None:
                            series_map[str(series_id_element.value)].append(file_path)
                    except Exception as e:
                        print(f"  Warning: Error reading {file_path}: {e}. Skipping.")

    if not series_map:
        print(f"  Warning: No series found based on tag '{series_identifier_config_val}'.")
    else:
        print(f"  Found {len(series_map)} unique series values for tag '{series_identifier_config_val}'.")

    return series_map


def compare_parameter_values(actual_value, expected_config, param_config_key, display_label):
    """
    Compares an actual DICOM value with the expected value from config.
    Can check a specific index of a list if 'index' is in expected_config.
    """
    expected_value = expected_config["expected"]
    tolerance = expected_config.get("tolerance")
    index_to_check = expected_config.get("index") # Get the new 'index' field

    if actual_value is None:
        return False, f"Tag '{display_label}' (key: {param_config_key}) not found in DICOM file."

    if isinstance(actual_value, pydicom.multival.MultiValue):
        actual_value = list(actual_value)

    # --- NEW LOGIC FOR INDEX CHECKING ---
    if index_to_check is not None:
        if not isinstance(actual_value, list):
            return False, f"Config expects a list to check index {index_to_check}, but tag value is not a list (it is {type(actual_value)})."
        
        # Clean the list by removing empty strings, which are common in GE private tags
        cleaned_list = [v for v in actual_value if str(v).strip() != '']
        
        if index_to_check >= len(cleaned_list):
            return False, f"Index {index_to_check} is out of bounds for the list of values (length: {len(cleaned_list)}). Values: {cleaned_list}"
        
        # Overwrite actual_value with the single element we want to check.
        # The rest of the function will now compare this single value.
        actual_value = cleaned_list[index_to_check]
    # --- END OF NEW LOGIC ---

    try:
        if isinstance(expected_value, (int, float)):
            current_actual_value = actual_value[0] if isinstance(actual_value, list) and len(actual_value) == 1 else actual_value
            actual_value_dec = Decimal(str(current_actual_value))
            expected_value_dec = Decimal(str(expected_value))
            
            if tolerance is not None:
                tolerance_dec = Decimal(str(tolerance))
                if not (expected_value_dec - tolerance_dec <= actual_value_dec <= expected_value_dec + tolerance_dec):
                    return False, f"Value {actual_value_dec} is outside tolerance range [{expected_value_dec - tolerance_dec}, {expected_value_dec + tolerance_dec}]"
            elif actual_value_dec != expected_value_dec:
                return False, f"Value {actual_value_dec} is not equal to expected {expected_value_dec}"

        elif isinstance(expected_value, list):
            # This block now only runs if we are comparing the full list (i.e., 'index' was not specified)
            if not isinstance(actual_value, list) or len(actual_value) != len(expected_value):
                return False, f"Type/length mismatch: Expected list of length {len(expected_value)}, got {actual_value}"
            
            for i, (exp_item, act_item) in enumerate(zip(expected_value, actual_value)):
                # Simplified item-wise comparison loop
                if str(act_item).strip() != str(exp_item).strip():
                    return False, f"Item {i}: Actual '{str(act_item).strip()}' != Expected '{str(exp_item).strip()}'"

        elif isinstance(expected_value, str):
            if str(actual_value).strip() != expected_value.strip():
                return False, f"Value '{str(actual_value).strip()}' is not equal to expected string '{expected_value.strip()}'"
        else:
            return False, f"Unsupported expected value type in config: {type(expected_value)}"

    except (InvalidOperation, ValueError, TypeError) as e:
        return False, f"Type mismatch or conversion error for '{display_label}': {e}"
    
    # Format actual_value for reporting
    formatted_actual = str(actual_value).strip() if isinstance(actual_value, str) else actual_value

    return True, f"Expected {expected_value}" + (f" (tol {tolerance})" if tolerance is not None else "") + (f" at index {index_to_check}" if index_to_check is not None else "") + f", Actual {formatted_actual}"


def validate_series_parameters(dicom_dataset, series_rule, series_identifier_value_for_log):
    """Validates parameters for a single series against its rule."""
    errors = 0
    warnings = 0
    
    print(f"\nProcessing Series Identifier Value: '{series_identifier_value_for_log}'")
    print(f"  (Using DICOM file: {dicom_dataset.filename})")
    print("-" * 80)

    params_to_check = series_rule.get("parameters_to_check", {})
    if not params_to_check:
        print("  [INFO] No parameters specified for checking in this rule.")
        return errors, warnings

    for param_config_key, expected_config in params_to_check.items():
        param_tag = parse_tag(param_config_key)
        display_label = expected_config.get("label", param_config_key)

        if param_tag is None:
            print(f"  [CONFIG_WARNING] Parameter '{display_label}': Invalid tag format. Skipping.")
            warnings +=1
            continue
        
        if "expected" not in expected_config:
            print(f"  [CONFIG_WARNING] Parameter '{display_label}': Missing 'expected' value. Skipping.")
            warnings +=1
            continue

        dicom_element = dicom_dataset.get(param_tag, None)
        actual_value = dicom_element.value if dicom_element else None
        
        is_match, message = compare_parameter_values(actual_value, expected_config, param_config_key, display_label)

        if actual_value is None and "not found" in message : 
             print(f"  [WARNING] {message}")
             warnings += 1
        elif not is_match:
            print(f"  [ERROR] {display_label}: {message}")
            errors += 1
        else: 
            print(f"  [OK] {display_label}: {message}")
            
    return errors, warnings

def main():
    parser = argparse.ArgumentParser(description="Validate DICOM acquisition parameters against a configuration file.")
    parser.add_argument("--dicom_dir", required=True, help="Path to the directory containing DICOM files.")
    parser.add_argument("--config", required=True, help="Path to the JSON configuration file.")
    
    args = parser.parse_args()

    print("DICOM Parameter Validator (v4 - with Index Checking)")
    print("==================================================")
    print(f"Configuration File: {args.config}")
    
    config_data = load_config(args.config)
    series_identifier_tag_from_config = config_data["series_identifier_tag"]
    
    series_map = find_dicom_series(args.dicom_dir, series_identifier_tag_from_config)

    if not series_map:
        print("\nNo DICOM series found to match configuration rules. Exiting.")
        sys.exit(0)

    total_errors = 0
    total_warnings = 0
    series_results_summary = {}
    validated_series_count = 0

    for series_id_val_from_scan, file_paths in series_map.items():
        matching_rules = [rule for rule in config_data["series_rules"] if str(rule["series_identifier_value"]).strip() == str(series_id_val_from_scan).strip()]

        if not matching_rules:
            continue
        
        validated_series_count +=1
        series_rule = matching_rules[0]
        first_file_path = file_paths[0]
        
        try:
            dicom_dataset = pydicom.dcmread(first_file_path, stop_before_pixels=True)
        except Exception as e:
            print(f"\nError reading DICOM file {first_file_path}: {e}. Skipping series.", file=sys.stderr)
            total_errors +=1
            series_results_summary[str(series_id_val_from_scan)] = {'errors': 1, 'warnings': 0, 'status': 'Read Error'}
            continue
            
        errors, warnings = validate_series_parameters(dicom_dataset, series_rule, series_id_val_from_scan)
        total_errors += errors
        total_warnings += warnings
        series_results_summary[str(series_id_val_from_scan)] = {'errors': errors, 'warnings': warnings, 'status': 'Validated'}

    if validated_series_count == 0:
        print(f"\nNo series found in '{args.dicom_dir}' matched any 'series_identifier_value' in the configuration file.")

    print("\n\nValidation Summary:")
    print("-------------------")
    if not series_results_summary:
        print("No series were processed or matched configuration rules.")
    else:
        for series_id_val, results in series_results_summary.items():
            print(f"Series '{series_id_val}': {results['errors']} error(s), {results['warnings']} warning(s)")
    
    print(f"\nTotal across all validated series: {total_errors} error(s), {total_warnings} warning(s).")
    print("\nValidation Complete.")

if __name__ == "__main__":
    main()
