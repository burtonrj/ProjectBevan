from tqdm import tqdm
from warnings import warn
import requests
import time
import os


def get_credentials(path: str):
    """
    Fetch credentials from text file. See C&V IT services for access.

    Parameters
    ----------
    path: str

    Returns
    -------
    str, str
        username, password
    """
    with open(path, "r") as login:
        username, pw = login.read().splitlines()
        return username.rstrip("\n"), pw.rstrip("\n")


def get_token(username: str,
              pw: str,
              filehost: str = "securefileshare.wales.nhs.uk") -> dict:
    """
    Fetch Bearer token for securefileshare

    Parameters
    ----------
    username: str
    pw: str
    filehost: str

    Returns
    -------
    dict
        Dictionary. Access token under key "access_token"
    """
    endpoint = f"https://{filehost}/api/v1/token"
    data = {"grant_type": "password",
            "username": username,
            "password": pw}
    token = requests.post(endpoint,
                          data=data,
                          verify=False)
    assert token.status_code == 200, f"Request failed. Error code: {token.status_code}"
    json = token.json()
    token.close()
    return json


def _fetch_page(token: dict,
                endpoint: str,
                sleep: int,
                max_repeats: int) -> dict:
    """
    Fetch a single page from the securefileshare site.

    Parameters
    ----------
    token: dict
        Dictionary containing 'access_token'
    endpoint: str
        API endpoint
    sleep: int
        Delay in seconds between requests
    max_repeats: int
        Maximum attempts

    Returns
    -------
    dict
        Dictionary of page content. If max_attempts exceeded, TimeoutError raised.
    """
    header = {"Authorization": f"Bearer {token}"}
    for i in range(max_repeats):
        json = requests.get(endpoint,
                            headers=header).json()
        if json.get("message") != "Authorization has been denied for this request.":
            if json.get("message") != "Internal Server Error":
                if json.get("items") is not None:
                    return json
        time.sleep(sleep)
    raise TimeoutError("Failed to fetch page...timed out")


def get_pages(directory_id: str = "662104718",
              filehost: str = "securefileshare.wales.nhs.uk",
              sleep: int = 2,
              max_repeats: int = 5) -> dict:
    """
    Fetch a summary of all pages on securefileshare

    Parameters
    ----------
    directory_id: str
        Target directory ID on securefileshare
    filehost: str, default="securefileshare.wales.nhs.uk"
        Host address
    sleep: int, default = 2
        Delay between requests
    max_repeats: int
        Maximum number of attempts

    Returns
    -------
    dict
        {page_number: page_content[dict]}
    """
    username, pw = get_credentials(f"{os.getcwd()}/login.txt")
    token = get_token(username, pw, filehost).get("access_token")
    assert token is not None, "Access token is null"
    # First determine how many pages there are...
    endpoint = f"https://{filehost}/api/v1/folders/{directory_id}/files?page=1"
    print("---- Determining number of pages ----")
    json = _fetch_page(token, endpoint, sleep, max_repeats)
    page_n = json.get("paging").get("totalPages")
    print(f"...total pages: {page_n}")
    # For each page, go through and fetch the file names
    pages = dict()
    print("---- Summarising page content ----")
    for i in tqdm(range(1, page_n + 1)):
        endpoint = f"https://{filehost}/api/v1/folders/{directory_id}/files?page={i}"
        try:
            pages[i] = _fetch_page(token, endpoint, sleep, max_repeats).get("items")
        except TimeoutError:
            username, pw = get_credentials(f"{os.getcwd()}/login.txt")
            token = get_token(username, pw, filehost).get("access_token")
            pages[i] = _fetch_page(token, endpoint, sleep, max_repeats).get("items")
        time.sleep(sleep)
    return pages


def _write_csv(text: str,
               write_path: str):
    """
    Write file to csv

    Parameters
    ----------
    text: str
    write_path: str

    Returns
    -------
    None
    """
    with open(write_path, "w") as file:
        file.write(text)


def _download(token: str,
              endpoint: str,
              file_name: str,
              output_dir: str,
              sleep: int = 2,
              max_repeats: int = 5):
    """
    Download a file from securefileshare

    Parameters
    ----------
    token: str
        Bearer access token
    endpoint: str
        API endpoint where file is found
    file_name: str
        ID of file to download
    output_dir: str
        Where to download the file too
    sleep: int, default = 2
        Delay in seconds between requests
    max_repeats: int, default=5
        Max number of attempts

    Returns
    -------
    None
        Writes file to disk or raises TimeoutError is max_repeats exceeded.
    """
    header = {"Authorization": f"Bearer {token}"}
    for i in range(max_repeats):
        file = requests.get(endpoint, headers=header).text
        if file is None:
            time.sleep(sleep)
            continue
        if len(file) == 0:
            time.sleep(sleep)
            continue
        if "Authorization has been denied for this request" in file:
            time.sleep(sleep)
            continue
        if "Internal Server Error" in file:
            time.sleep(sleep)
            continue
        _write_csv(file, f"{output_dir}/{file_name}.csv")
        return None
    raise TimeoutError("Failed to fetch file...timed out")


def get_files(pages: dict,
              output_dir: str = "data",
              directory_id: str = "662104718",
              filehost: str = "securefileshare.wales.nhs.uk",
              sleep: int = 3,
              max_repeats: int = 10):
    """
    Given a dictionary of page content (as generated by 'get_pages') download all files in target directory
    on securefileshare

    Parameters
    ----------
    pages: dict
        Dictionary of page content as generated by 'get_pages'
    output_dir: str, default = "data" (in working directory)
        Where to store downloaded files locally)
    directory_id: str
        Name of the target directory on securefileshare
    filehost: str, default = "securefileshare.wales.nhs.uk"
        URL of filehost
    sleep: int, default = 3
        delay in seconds between requests
    max_repeats: int, default = 10
        Maximum number of attempts per file

    Returns
    -------
    None
    """
    username, pw = get_credentials(f"{os.getcwd()}/login.txt")
    token = get_token(username, pw, filehost).get("access_token")
    assert token is not None, "Access token is null"
    output_dir = os.path.join(os.getcwd(), output_dir)
    for i, page_content in pages.items():
        if page_content is None:
            warn(f"Page {i} is empty!")
            continue
        print(f"---- Fetching files from page {i} ----")
        file_names = [x.get("name") for x in page_content]
        file_ids = [x.get("id") for x in page_content]
        if len(file_names) == 0:
            warn(f"No page content for page {i}")
            continue
        files = list(zip(file_names, file_ids))
        existing_files = os.listdir(output_dir)
        for file_name, file_id in tqdm(files):
            if f"{file_name}.csv" in existing_files:
                continue
            endpoint = f"https://{filehost}/api/v1/folders/{directory_id}/files/{file_id}/download"
            try:
                _download(token=token,
                          endpoint=endpoint,
                          file_name=file_name,
                          output_dir=output_dir,
                          sleep=sleep,
                          max_repeats=max_repeats)
            except TimeoutError:
                username, pw = get_credentials(f"{os.getcwd()}/login.txt")
                token = get_token(username, pw, filehost).get("access_token")
                assert token is not None, "Access token is null"
                try:
                    _download(token=token,
                              endpoint=endpoint,
                              file_name=file_name,
                              output_dir=output_dir,
                              sleep=sleep,
                              max_repeats=max_repeats)
                except TimeoutError:
                    warn(f"Failed to fetch file {file_name} after multiple attempts...")
            time.sleep(sleep)
    print("COMPLETE!")





