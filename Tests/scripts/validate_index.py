"""Run validation on the index.json file.

Check index.json file inside the index.zip archive in the cloud.
Validate no missing ids are found and that all packs have a non negative price.
Validate commit hash is in master's history.
"""
import argparse
import sys
import os
from typing import Tuple

from Tests.Marketplace.marketplace_services import init_storage_client, load_json, get_content_git_client
from Tests.Marketplace.upload_packs import download_and_extract_index
from Tests.Marketplace.marketplace_constants import GCPConfig, CONTENT_ROOT_PATH
from Tests.scripts.utils.log_util import install_logging
from Tests.scripts.utils import logging_wrapper as logging
from pprint import pformat


def options_handler():
    parser = argparse.ArgumentParser(description='Run validation on the index.json file.')
    parser.add_argument('-e', '--extract_path',
                        help=f'Full path of folder to extract the {GCPConfig.INDEX_NAME}.zip to',
                        required=True)
    parser.add_argument('-pb', '--production_bucket_name', help='Production bucket name', required=True)
    parser.add_argument('-sb', '--storage_base_path', help="Storage base path of the directory to upload to.",
                        required=False)
    parser.add_argument('-sa', '--service_account', help='Path to gcloud service account', required=True)
    parser.add_argument('-c', '--circle_branch', help="CircleCi branch of current build", required=True)
    options = parser.parse_args()
    return options


def log_message_if_statement(statement: bool, error_message: str, success_message: str = None) -> bool:
    """Log error message if statement is false, Log success otherwise

    Args:
        statement: The boolean statement to check.
        error_message: The error message to log if statement is false
        success_message: The success message to log if statement is true

    Returns: The statements boolean value.
    """
    if not statement:
        logging.error(error_message)
    elif success_message:
        logging.success(success_message)
    return statement


def check_index_data(index_data: dict) -> bool:
    """Check index.json file inside the index.zip archive in the cloud.

    Validate by running verify_pack on each pack.

    Args:
        index_data: Dictionary of the index.json contents.

    Returns: True if all packs are valid, False otherwise.
    """
    logging.info("Found index data in index file. Checking...")
    logging.debug(f"Index data is:\n {pformat(index_data)}")

    packs_list_exists = log_message_if_statement(statement=(len(index_data.get("packs", [])) != 0),
                                                 error_message="Found 0 packs in index file."
                                                               "\nAborting the rest of the check.")
    # If all packs are gone, return False
    if not packs_list_exists:
        return False

    packs_are_valid = True
    for pack in index_data["packs"]:
        pack_is_good = verify_pack(pack)
        if not pack_is_good:
            packs_are_valid = False

    return packs_are_valid


def verify_pack(pack: dict) -> bool:
    """Verify the pack id is not empty and it's price is non negative.

    Args:
        pack: The pack to verify.

    Returns: True if pack is valid, False otherwise.
    """
    id_exists = log_message_if_statement(statement=(pack.get("id", "") not in ("", None)),
                                         error_message="There is a missing pack id.")
    price_is_valid = log_message_if_statement(statement=(pack.get("price", -1) >= 0),
                                              error_message=f"The price on the pack {pack.get('id', '')} is invalid.",
                                              success_message=f"The price on the pack {pack.get('id', '')} is valid.")
    return all([id_exists, price_is_valid])


def check_commit_in_branch_history(index_commit_hash: str, circle_branch: str) -> bool:
    """Assert commit hash is in branch's commit history.

    Args:
        index_commit_hash: commit hash
        circle_branch: circle branch of current run

    Returns: True if commit hash is in branch's commit history, False otherwise.
    """
    content_repo = get_content_git_client(CONTENT_ROOT_PATH)
    branch_commits = list(map(lambda commit: commit.hexsha, list(content_repo.iter_commits(f"origin/{circle_branch}"))))

    return log_message_if_statement(statement=(index_commit_hash in branch_commits),
                                    error_message=f"Commit hash {index_commit_hash} is not in {circle_branch} history",
                                    success_message="Commit hash in index file is valid.")


def get_index_json_data(service_account: str, production_bucket_name: str, extract_path: str, storage_base_path: str) \
        -> Tuple[dict, str]:
    """Retrieve the index.json file from production bucket.

    Args:
        service_account: Path to gcloud service account
        production_bucket_name: Production bucket name
        extract_path: Full path of folder to extract the index.zip to
        storage_base_path: The base path in the bucket

    Returns:
        (Dict: content of the index.json, Str: path to index.json)
    """
    logging.info('Downloading and extracting index.zip from the cloud')

    storage_client = init_storage_client(service_account)
    production_bucket = storage_client.bucket(production_bucket_name)
    index_folder_path, _, _ = download_and_extract_index(production_bucket, extract_path, storage_base_path)

    logging.info("Retrieving the index file")
    index_file_path = os.path.join(index_folder_path, f"{GCPConfig.INDEX_NAME}.json")
    index_data = load_json(index_file_path)

    return index_data, index_file_path


def main():
    install_logging("Validate index.log", logger=logging)
    options = options_handler()
    exit_code = 0
    index_data, index_file_path = get_index_json_data(
        service_account=options.service_account, production_bucket_name=options.production_bucket_name,
        extract_path=options.extract_path, storage_base_path=options.storage_base_path
    )

    # Validate index.json file
    index_is_valid = check_index_data(index_data)
    log_message_if_statement(statement=index_is_valid,
                             error_message=f"The packs in the {index_file_path} file were found invalid.",
                             success_message=f"{index_file_path} file was found valid")

    # Validate commit hash in master history
    commit_hash_is_valid = log_message_if_statement(statement=("commit" in index_data),
                                                    error_message="No commit field was found in the index.json")
    if commit_hash_is_valid:
        commit_hash_is_valid = check_commit_in_branch_history(index_data.get("commit", ""), options.circle_branch)

    if not all([index_is_valid, commit_hash_is_valid]):
        logging.critical("Index content is invalid. Aborting.")

    # Deleting GCS PATH before exit
    if exit_code == 1 and os.path.exists(options.service_account):
        os.remove(options.service_account)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
