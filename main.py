import os
import requests
from time import sleep
from flask import Flask
from datetime import datetime
from dotenv import load_dotenv
from selenium import webdriver
from twilio.rest import Client
from flask_sqlalchemy import SQLAlchemy
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from sqlalchemy.dialects.postgresql import JSON
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException

load_dotenv('.env')

now = datetime.now()
today_date = now.strftime("%m/%d/%Y")

app = Flask(__name__)

# CREATE DATABASE
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URI')
# Optional: But it will silence the deprecation warning in the console.
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# CREATE TABLE
class Codes(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(250), nullable=False)
    code = db.Column(db.String(250), unique=True, nullable=False)
    platform = db.Column(db.String(250), nullable=False)
    game = db.Column(db.String(250), nullable=False)
    reward = db.Column(db.String(250), nullable=False)
    json_column = db.Column(JSON)


# db.create_all()  # uncomment when running for the first time to create table

# request data from shift archive
req = requests.get(url='https://shift.orcicorn.com/index.json')
results = req.json()[0]['codes']

# required option for selenium to run on heroku
chrome_options = webdriver.ChromeOptions()
chrome_options.binary_location = os.environ.get('GOOGLE_CHROME_BIN')
chrome_options.add_argument('--headless')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--no-sandbox')
driver = webdriver.Chrome(service=Service(executable_path=os.environ.get("CHROMEDRIVER_PATH")), options=chrome_options)

driver.get("https://shift.gearboxsoftware.com/rewards")

# logs into user gearbox account
user_email = driver.find_element(By.ID, "user_email")
user_email.send_keys(os.environ.get('USER_EMAIL'))
user_password = driver.find_element(By.ID, "user_password")
user_password.send_keys(os.environ.get('USER_PASSWORD'))
user_password.send_keys(Keys.RETURN)
print(f'Successfully signed into {os.environ.get("USER_EMAIL")}')

try:
    driver.find_element(By.XPATH, '//*[@id="cookie-banner"]/div[2]/button').click()  # closes cookie banner
except NoSuchElementException:
    pass


successful_codes_count = 0  # counter for codes redeemed

# checks if code exist in database
for key in results:
    check_if_code_exists = db.session.query(Codes.id).filter_by(code=key['code']).first() is not None

    if check_if_code_exists is not True:

        print(f"Trying to redeem {key['code']}")
        code_input = driver.find_element(By.ID, "shift_code_input")
        code_input.send_keys(key['code'])
        sleep(1)
        check_button = driver.find_element(By.ID, "shift_code_check")
        check_button.click()
        sleep(1.5)
        game_title = driver.find_element(By.XPATH, '//*[@id="code_results"]/h2').text
        print(f'{game_title} - ({key["reward"]})')

        try:
            driver.find_element(By.XPATH, "//input[@value='Redeem for Xbox Live']").click()
            sleep(2)

            new_code = Codes(id=len(Codes.query.all()) + 1, date=today_date, code=key['code'], platform='Xbox',
                             game=key['game'], reward=key['reward'],
                             json_column={'id': len(Codes.query.all()) + 1, 'date': today_date, 'code': key['code'],
                                          'platform': 'Xbox', 'game': key['game'], 'reward': key['reward']})
            db.session.add(new_code)
            db.session.commit()

        except NoSuchElementException:
            try:
                driver.find_element(By.XPATH, "//input[@value='Redeem for PSN']").click()
                sleep(2)

                new_code = Codes(id=len(Codes.query.all()) +1, date=today_date, code=key['code'], platform="Playstation",
                                 game=game_title, reward=key['reward'],
                                 json_column={'id': len(Codes.query.all()) + 1, 'date': today_date, 'code': key['code'],
                                              'platform': 'Playstation', 'game': key['game'], 'reward': key['reward']})
                db.session.add(new_code)
                db.session.commit()

            except NoSuchElementException:
                driver.find_element(By.XPATH, "//input[@value='Redeem for Steam']").click()
                sleep(2)

                new_code = Codes(id=len(Codes.query.all()) +1, date=today_date, code=key['code'], platform="Steam",
                                 game=game_title, reward=key['reward'],
                                 json_column={'id': len(Codes.query.all()) + 1, 'date': today_date, 'code': key['code'],
                                              'platform': 'Steam', 'game': key['game'], 'reward': key['reward']})
                db.session.add(new_code)
                db.session.commit()

        successful_codes_count += 1

if successful_codes_count != 0:
    # sends text with number of code(s) redeemed
    account_sid = os.environ.get('ACCOUNT_SID')
    auth_token = os.environ.get('AUTH_TOKEN')
    client = Client(account_sid, auth_token)

    message = client.messages \
        .create(
        body=f"Successfully redeemed {successful_codes_count} SHiFT Code(s)",
        from_=os.environ.get('TWILIO_NUMBER'),
        to=os.environ.get('NUMBER_1')
    )



driver.quit()
