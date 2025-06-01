import sys
import pydicom
from pydicom.errors import InvalidDicomError

def get_asset_factor(dicom_path):
    """
    Reads a DICOM file from a GE scanner and prints the ASSET acceleration factor.

    The ASSET factor is derived from the GE private tag (0043, 1083).
    This tag stores the reciprocal of the in-plane acceleration factor.
    """
    # Define the private DICOM tag for GE's ASSET R Factors
    asset_tag = (0x0043, 0x1083)

    try:
        # Read the DICOM file
        dicom_dataset = pydicom.dcmread(dicom_path)

        # Check if the ASSET tag exists in the dataset
        if asset_tag in dicom_dataset:
            # The tag's value is often a multi-value (MV) list,
            # with the first value being the in-plane factor.
            # It stores the reciprocal of the acceleration factor.
            asset_r_value = dicom_dataset[asset_tag].value

            # Handle both single and multi-valued tags
            if isinstance(asset_r_value, (list, pydicom.multival.MultiValue)):
                reciprocal_factor = float(asset_r_value[0])
            else:
                reciprocal_factor = float(asset_r_value)

            # Calculate the actual acceleration factor
            if reciprocal_factor > 0:
                asset_factor = 1 / reciprocal_factor
                # Format to a clean integer if it's a whole number (e.g., 2.0 -> 2)
                if asset_factor.is_integer():
                    print(f"✅ The ASSET acceleration factor is: {int(asset_factor)}")
                else:
                    print(f"✅ The ASSET acceleration factor is: {asset_factor:.2f}")
            else:
                print(f"⚠️ ASSET tag found, but its value is {reciprocal_factor}, which cannot be inverted.")

        else:
            print("❌ The GE ASSET factor tag (0043, 1083) was not found in this DICOM file.")

    except InvalidDicomError:
        print(f"Error: The file at '{dicom_path}' is not a valid DICOM file.")
    except FileNotFoundError:
        print(f"Error: The file at '{dicom_path}' was not found.")
    except ZeroDivisionError:
        print("Error: The value in the ASSET tag was zero, cannot calculate acceleration factor.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    # Ensure a file path is provided as a command-line argument
    if len(sys.argv) != 2:
        print("Usage: python check_asset.py <path_to_your_dicom_file>")
        sys.exit(1)

    dicom_file_path = sys.argv[1]
    get_asset_factor(dicom_file_path)
    