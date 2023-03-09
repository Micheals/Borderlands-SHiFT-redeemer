import os
import pytz
import logging
import requests
from time import sleep
from datetime import datetime
from dotenv import load_dotenv
from selenium import webdriver
from twilio.rest import Client
from pymongo import MongoClient
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains


def load_env_vars(env_path=".env"):
    """Loads environment variables from a .env file"""
    load_dotenv(env_path)


def convert_to_gmt(local_tz):
    # Get the current date and time in the local timezone
    now = datetime.now(pytz.timezone(local_tz))

    # Convert the local timezone to GMT
    gmt = pytz.timezone('GMT')
    gmt_now = now.astimezone(gmt)

    # Format the GMT time as a string
    gmt_now_str = gmt_now.strftime("%m/%d/%Y")

    return gmt_now_str


def setup_logger(log_level):
    # Create a logger object
    logger = logging.getLogger(__name__)
    logger.setLevel(log_level)

    # Create a file handler and set its log level
    fh = logging.FileHandler('SHiFT_Redeemer.log')
    fh.setLevel(log_level)

    # Create a console handler and set its log level
    ch = logging.StreamHandler()
    ch.setLevel(log_level)

    # Create a formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - LINENO: %(lineno)d - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


def create_mongo_client(uri):
    """Creates a MongoClient object and returns it"""
    print('Connecting to database...')
    return MongoClient(uri)


def get_transactions_collection(client, db_name, collection_name):
    """Connects to the specified MongoDB database and returns the specified collection"""
    db = client[db_name]
    transactions = db[collection_name]
    return transactions


def get_shift_codes_from_archive():
    """Returns shift codes from shift archive"""
    req = requests.get(url='https://shift.orcicorn.com/index.json')
    results = req.json()[0]['codes']
    return results


# commented out until problematic code is removed from archive
# def check_table_for_code(results, transactions):
#     """Queries table to see if code exists"""
#     all_codes_in_db = {i['code'] for i in transactions.find({})}
#     code_not_in_table = [shift_code for shift_code in results if shift_code['code'] not in all_codes_in_db]
#     if not code_not_in_table:
#         print("No new shift codes found in archive. Exiting program.")
#         exit()
#     return code_not_in_table


def check_table_for_code(results, transactions):
    """Queries table to see if code exists"""
    all_codes_in_db = {i['code'] for i in transactions.find({})}
    code_not_in_table = []
    for shift_code in results:
        if shift_code['code'] == 'TJRB3-CKZRB-F5JK5-B3BBB-3FZC9':
            continue  # skip this code
        if shift_code['code'] not in all_codes_in_db:
            code_not_in_table.append(shift_code)
    if not code_not_in_table:
        print("No new shift codes found in archive. Exiting program...")
        exit()
    return code_not_in_table


def create_webdriver(headless=True, sandbox=True):
    """Connects to ChromeDriver and returns the driver"""
    # required options for selenium to run on heroku
    chrome_options = webdriver.ChromeOptions()
    chrome_options.binary_location = os.environ.get('GOOGLE_CHROME_BIN')
    if headless:
        chrome_options.add_argument('--headless')
    if sandbox:
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--no-sandbox')
    # driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver = webdriver.Chrome(executable_path=os.environ.get("CHROMEDRIVER_PATH"), options=chrome_options)
    return driver


def gearbox_login(driver):
    """Logs into user gearbox account"""

    user_email = driver.find_element(By.ID, "user_email")
    user_email.send_keys(os.environ.get('USER_EMAIL'))
    user_password = driver.find_element(By.ID, "user_password")
    user_password.send_keys(os.environ.get('USER_PASSWORD'))
    user_password.send_keys(Keys.RETURN)
    print(f'Successfully signed into {os.environ.get("USER_EMAIL")}')


def accept_cookies(driver):
    """Accepts the cookie policy banner."""
    try:
        cookie_button = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="cookie-banner"]/div[2]/button')))
        cookie_button.click()
    except TimeoutException:
        print("Error: Could not find cookie banner button within 5 seconds")


def enter_code(driver, code, logger):
    logger.info(f"-----------Trying to redeem {code}-----------")
    code_input = driver.find_element(By.ID, "shift_code_input")
    code_input.send_keys(code)
    sleep(1)
    check_button = driver.find_element(By.ID, "shift_code_check")
    check_button.click()
    sleep(1)


def is_code_valid(driver, logger):
    try:
        code_results = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'code_results')))
        error_messages = ['code has expired', 'code does not exist', 'not a valid SHiFT code']
        if any(msg in code_results.text for msg in error_messages):
            logger.info(code_results.text)
            driver.refresh()
            return False
    except:
        pass
    return True


def insert_to_database(code, platform, game_title, driver, transactions, logger):
    today_date = convert_to_gmt('US/Eastern')
    """Inserts a SHiFT code transaction into a MongoDB database using the provided transactions collection object."""

    # Get the reward text for the redeemed SHiFT code
    gearbox_reward = driver.find_element(By.XPATH, '//dt').text

    # Log information about the redemption and the reward received
    logger.info(f'Code redeemed for {game_title} on {platform}')
    logger.info(f'Reward: {gearbox_reward}.')

    # Create a dictionary representing the transaction data
    doc_data = {
        '_id': transactions.count_documents({}) + 1,  # Generate new _id by counting the number of docs and adding 1
        'date': today_date,  # Store the current date and time
        'code': code,  # Store the redeemed SHiFT code
        'platform': platform,  # Store the platform the SHiFT code was redeemed on
        'game': game_title,  # Store the name of the game the SHiFT code was redeemed for
        'reward': gearbox_reward  # Store the reward received for redeeming the SHiFT code
    }

    # Insert the transaction data into the MongoDB database
    transactions.insert_one(doc_data)

    # Log that the transaction has been successfully inserted into the database
    logger.info(f'{code} has been inserted into database.')


def redeem_code(driver, code, transactions, logger):
    """Redeems a SHiFT code on the specified platforms in order."""

    count = 0
    while True:
        try:
            enter_code(driver, code, logger)

            # checks if code is expired, invalid, or doesn't exist
            if not is_code_valid(driver, logger):
                break

            # finds all available redeem options and returns a list
            all_buttons = driver.find_elements(By.CLASS_NAME, 'redeem_button')

            action = ActionChains(driver)

            if count < len(all_buttons):
                action.move_to_element(all_buttons[count]).perform()

                # highlights buttons red
                driver.execute_script("arguments[0].style.border='3px solid red'", all_buttons[count])

                # gets platform from value attribute of element (e.g. PNS, Steam. Xbox)
                platform = all_buttons[count].get_attribute('value').split('Redeem for ')[1].replace('Xbox Live', 'Xbox')
                logger.info(f'Redeeming for {platform}.')
                # input('next')

                # Find the parent element of the submit button and search for the first h2 tag
                submit_button = all_buttons[count]
                parent_element = submit_button.find_element(By.XPATH, '..')
                h2_tag = parent_element.find_element(By.XPATH, './preceding::h2[1]')
                logger.info(f'Redeeming code for {h2_tag.text}')

                h2_text_before_click = h2_tag.text  # Capture the h2 tag text before clicking the submit button
                submit_button.click()
                count += 1

                # Check if the error messages appear on page
                try:
                    # if code has already been redeemed, then move on to the next interation in all_button list
                    banner = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'alert'))).text
                    if 'code has already been redeemed' in banner:
                        logger.info(f'Code has already been redeemed for {h2_text_before_click} on {platform}')
                        if count == len(all_buttons):
                            logger.info('All redemption options have been exhausted!')
                            sleep(3)
                            # driver.refresh()
                            break
                        continue

                    if 'launch a SHiFT-enabled title first!' in banner:
                        critical_msg = 'To continue to redeem SHiFT codes, please launch a SHiFT-enabled title first!'
                        logger.critical(critical_msg)
                        send_sms(error_message=critical_msg)
                        exit()

                except Exception as e:
                    logger.error(e)
                    pass

                # logs code into database
                insert_to_database(code, platform, h2_text_before_click, driver, transactions, logger)

                if count == len(all_buttons):
                    logger.info('All redemption options have been exhausted!')
                    # driver.refresh()
                    break

        except Exception as e:
            logger.error(f'Encountered error: {e}')
            count += 1
            return


def send_sms(redeemed_count=None, error_message=None):
    account_sid = os.environ.get('ACCOUNT_SID')
    auth_token = os.environ.get('AUTH_TOKEN')
    client = Client(account_sid, auth_token)

    if error_message:
        message_body = error_message
    elif redeemed_count is not None and redeemed_count > 0:
        message_body = f"Successfully redeemed {redeemed_count} SHiFT Code(s)"
    else:
        return

    message = client.messages \
        .create(
        body=message_body,
        from_=os.environ.get('TWILIO_NUMBER'),
        to=os.environ.get('NUMBER_1')
    )


def main():
    """Logs into gearbox website and accepts the cookie policy banner.
    Selenium will then attempt to redeem the SHiFT codes"""
    # Load environment variables
    load_env_vars()

    logger = setup_logger(logging.DEBUG)

    # Get the latest SHiFT codes from the SHiFT archive
    shift_codes = get_shift_codes_from_archive()

    # Connect to MongoDB database and get the transactions collection
    client = create_mongo_client(os.environ.get('MONGODB_URI'))
    transactions = get_transactions_collection(client, 'Borderlands_SHiFT_CodesDB', 'SHiFT_Codes')

    # Check if the retrieved SHiFT codes from the archive already exist in the database
    new_codes = check_table_for_code(shift_codes, transactions)

    # Create a webdriver instance and navigate to the SHiFT rewards page
    driver = create_webdriver(headless=True)
    driver.get("https://shift.gearboxsoftware.com/rewards")

    # Log into the user's gearbox account
    gearbox_login(driver)

    # Accept the cookie policy banner
    accept_cookies(driver)

    # counts number of successful redemptions
    successful_redemption_count = 0

    for key in new_codes:
        # print(key)

        redeem_code(driver, key['code'], transactions, logger)
        successful_redemption_count += 1

    # sends txt message
    send_sms(redeemed_count=successful_redemption_count)


if __name__ == '__main__':
    main()
