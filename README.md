\# 🛠️ SDET Automation Test – Google Shopping Rating Checker



This project automates the process of searching for a book on \*\*Google Shopping\*\*, applying price \& rating filters, and checking if the \*\*second product found\*\* meets your minimum rating criteria.



It’s built for demo, practice, and real-world QA automation scenarios.  

Works with \*\*Selenium + Pytest\*\*, supports \*\*Chrome\*\* and \*\*Firefox\*\*, and can run \*\*headless or visible\*\*.



---



\## 🚀 What it does



1\. Opens Google Shopping with your search term.

2\. Sets a max price filter.

3\. Applies a minimum rating filter (⭐).

4\. Visits product pages one by one.

5\. Confirms that the \*\*second qualifying product\*\* has a rating ≥ `MIN\_RATING`.

6\. Saves a screenshot if something fails.



---



\## 📦 Requirements



\- Python \*\*3.10+\*\* (tested on 3.13)

\- \[pip](https://pip.pypa.io/en/stable/installation/)

\- \*\*Firefox\*\* or \*\*Chrome\*\* installed

\- `geckodriver` or `chromedriver` in PATH  

&nbsp; \*(Selenium Manager will usually handle this automatically)\*



---



\## ⚙️ Setup



```bash

\# Clone the repo

git clone https://github.com/your-user/sdet-automation-test.git

cd sdet-automation-test



\# Create \& activate a virtual environment

python -m venv venv

source venv/bin/activate      # Mac/Linux

venv\\Scripts\\activate         # Windows



\# Install dependencies

pip install -r requirements.txt



