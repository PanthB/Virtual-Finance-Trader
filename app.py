import os
import datetime


import sqlite3
from flask import Flask, flash, redirect, render_template, request, session
from flask_session.__init__ import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import login_required, lookup, c_lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Connect to SQLite database
con = sqlite3.connect("finance.db")
db = con.cursor()
# SQLite database has the following tables: 
# crypto with columns: id, user_id, cryptoName, amount, price, totalValue, symbol
# holdings (for stocks) with columns: id, user_id, companyName, shares, price, totalValue, symbol
# purchases with columns: id, user_id, cryptoName, company_name, shares, time, price, type
# users with columns: id, username, hash, cash

# API key must be set
if not os.environ.get("API_KEY"):
    try:
        os.environ["API_KEY"]="pk_2391dc231592460fa04fa1541a3ee575"
    except:
        raise RuntimeError("API_KEY not set")

@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    #using a row factory to access columns from the database by name 
    with sqlite3.connect("finance.db") as con:
        con.row_factory = sqlite3.Row
        db = con.cursor()

        userid = session["user_id"]

        #executing SQL statements with the execute method of the cursor         
        db.execute("SELECT * FROM holdings WHERE user_id = ?", (userid,))
        rows = db.fetchall()

        prices = []
        #loop through user's holdings and append price of each stock to list 
        for i in range(len(rows)):
            row = rows[i]["symbol"]
            final = lookup(row)['price']
            prices.append(final)

        grand_total = 0
        #loop through user's holdings and calculate total value including shares
        for j in range(len(rows)):
            total = prices[j]*rows[j]["shares"]
            grand_total = grand_total + total

        #obtain user's current cash balance
        def balance():
            db.execute("SELECT cash FROM users WHERE id = ?", (userid,))
            cashRows = db.fetchall()
            balance = cashRows[0]["cash"]
            con.commit()
            return float(balance)

        balance_var = balance()

        #function to return a tuple with number of crypto holdings, 
        #list of holdings that can be indexed, list of prices of each crypto, and total value of all crypto 
        def crypto():
            db.execute("SELECT * FROM crypto WHERE user_id = ?", (userid,))
            c_rows = db.fetchall()

            c_prices = []

            for i in range(len(c_rows)):
                row = c_rows[i]["symbol"]
                final = c_lookup(row)['price']
                c_prices.append(final)

            crypto_total = 0
            for j in range(len(c_rows)):
                total = c_prices[j]*c_rows[j]["amount"]
                crypto_total = crypto_total + total            

            c_length = len(c_rows)
            return c_length, c_rows, c_prices, crypto_total 
        
        
        c_tuple = crypto()

        grand_total = grand_total + balance_var + c_tuple[3]
        grand_total = usd(grand_total)
        balance_var = usd(balance_var)
        length = len(rows)
        c_length = c_tuple[0]
        c_rows = c_tuple[1]
        c_prices = c_tuple[2]

        return render_template("index.html", c_rows=c_rows, c_length=c_length, c_prices=c_prices, rows=rows, length=length, prices=prices, grand_total=grand_total, usd=usd, balance_var=balance_var)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    #Check if user sent a POST request by submitting the HTML form  
    if request.method == "POST":
        with sqlite3.connect("finance.db") as con:
            con.row_factory = sqlite3.Row            
            db = con.cursor()
            if request.form['purchase'] == "Buy Stock":
                symbol = request.form.get("symbol").upper()
                if lookup(symbol) is None or request.form.get("shares") is None:
                    flash("Invalid Stock")
                    return redirect("/buy")

                if request.form.get("shares")=="":
                    flash("Please enter a valid # of Shares")
                    return redirect("/buy")
                shares = int(request.form.get("shares"))

                price = float(lookup(symbol)['price'])
                userid = session["user_id"]
                db.execute("SELECT * FROM users WHERE id = ?", (userid,))
                rows = db.fetchall()
                cash = rows[0]["cash"]
                type_buy="Buy"
                current_time = datetime.datetime.now()

                total_cost = price*shares
                if cash<total_cost:
                    flash("Cannot afford")
                    return redirect("/buy")
                #update SQL database once purchase is validated  
                db.execute("INSERT INTO purchases (user_id, company_name, shares, time, price, type) VALUES(?, ?, ?, ?, ?, ?)", ((userid), str(lookup(symbol)['name']), int(shares), (current_time), float(price), (str(type_buy))))
                updatedCash = cash - total_cost
                db.execute("UPDATE users SET cash = ? WHERE id = ?", ((updatedCash), (userid)))
                def check():
                    db.execute("SELECT * FROM holdings WHERE symbol = ? AND user_id = ?", ((symbol), (userid)))
                    database = db.fetchall()
                    check_symbol = len(database)
                    if check_symbol!=0:
                        current_shares = database[0]["shares"]
                        total_shares = current_shares+shares
                        db.execute("UPDATE holdings SET shares = ? WHERE user_id = ? AND symbol = ?", ((total_shares), (userid), (symbol)))
                        con.commit()
                    else:
                        db.execute("INSERT INTO holdings (user_id, companyName, shares, price, totalValue, symbol) VALUES(?, ?, ?, ?, ?, ?)", ((userid), (lookup(symbol)['name']), (shares), (price), (total_cost), (symbol)))
                        con.commit()
                    flash('Purchase successful!')
                check()

                return redirect("/")
            #if the form with the name "purchase" does not have the value "Buy Stock", the user is buying crypto:
            else:                    
                c_symbol = request.form.get("c_symbol")
                if c_lookup(c_symbol) is None or request.form.get("amount") is None:
                    flash("Invalid Cryptocurrency")
                    return redirect("/buy")
                
                name = c_lookup(c_symbol)['name']
                amount = float(request.form.get("amount"))
                if amount=="":
                    flash("Please enter a valid amount")
                    return redirect("/buy")

                price = float(c_lookup(c_symbol)['price'])
                userid = session["user_id"]
                db.execute("SELECT * FROM users WHERE id = ?", (userid,))
                rows = db.fetchall()
                cash = rows[0]["cash"]
                type_buy="Buy"
                current_time = datetime.datetime.now()

                total_cost = price*amount
                if cash<total_cost:
                    flash("Cannot afford")
                    return redirect("/buy")

                db.execute("INSERT INTO purchases (user_id, company_name, shares, time, price, type) VALUES(?, ?, ?, ?, ?, ?)", ((userid), str(name), float(amount), (current_time), float(price), (str(type_buy))))
                updatedCash = cash - total_cost
                db.execute("UPDATE users SET cash = ? WHERE id = ?", ((updatedCash), (userid)))

                def check_c():
                    db.execute("SELECT * FROM crypto WHERE symbol = ? AND user_id = ?", ((c_symbol), (userid)))
                    database = db.fetchall()
                    check_symbol = len(database)
                    if check_symbol!=0:
                        current_amount = database[0]["amount"]
                        total = current_amount+amount
                        db.execute("UPDATE crypto SET amount = ? WHERE user_id = ? AND symbol = ?", ((total), (userid), (c_symbol)))
                        con.commit()
                    else:
                        db.execute("INSERT INTO crypto (user_id, cryptoName, amount, price, totalValue, symbol) VALUES(?, ?, ?, ?, ?, ?)", ((userid), (name), (amount), (price), (total_cost), (c_symbol)))
                        con.commit()
                check_c()
                flash('Purchase successful!')
                return redirect("/")

    else:
        return render_template("buy.html")

@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    with sqlite3.connect("finance.db") as con:
        con.row_factory = sqlite3.Row
        db = con.cursor()
        
        userid = session["user_id"]

        #Select all elements from purchases 
        db.execute("SELECT * FROM purchases WHERE user_id = ?", (userid,))
        stocks = db.fetchall()
        con.commit()

        return render_template("history.html", stocks=stocks, usd=usd)



@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    if session.get("_flashes"):
        flashes = session.get("_flashes")
        session.clear()
        session["_flashes"] = flashes
    else:
        session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        with sqlite3.connect("finance.db") as con:
            con.row_factory = sqlite3.Row   
            db = con.cursor()


            # Ensure username was submitted
            if not request.form.get("username"):
                flash("Please provide a valid username")
                return redirect("/login")

            # Ensure password was submitted
            elif not request.form.get("password"):
                flash("Please provide a valid password")
                return redirect("/login")

            # Query database for username
            username = request.form.get("username")
            db.execute("SELECT * FROM users WHERE username = ?", (username,))
            rows = db.fetchall()

            # Ensure username exists and password is correct
            if len(rows)!=1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
                flash("Invalid username and/or password")
                return redirect("/login")

            # Remember which user has logged in
            session["user_id"] = int(rows[0]["id"])
            con.commit()
            flash('You have successfully logged in!')
            # Redirect user to home page
            return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        if request.form['enter'] == "Get Stock Quote":
            symbol = request.form.get("symbol")
            if lookup(symbol) is None:
                flash("Please enter a valid stock symbol")
                return redirect("/quote")
            else:
                price = usd(lookup(symbol)['price'])
                name = lookup(symbol)['name']
                return render_template("quoted.html", price=price, name=name)
        
        else:
            c_symbol = request.form.get("c_symbol")
            if c_lookup(c_symbol) is None:
                flash("Enter a valid crypto symbol")
                return redirect("/quote")
            price = usd(c_lookup(c_symbol)['price'])
            name = c_lookup(c_symbol)['name']

            return render_template("quoted.html", price=price, name=name)

    else:
        return render_template("quote.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    session.clear()

    #if user submits registration form, check if username is unique and password is valid, then update database
    if request.method == "POST":
        with sqlite3.connect("finance.db") as con:
            con.row_factory = sqlite3.Row
            db = con.cursor()
            db.execute("SELECT * FROM users")
            user_list = db.fetchall()
            
            usernames = []
            for i in range(len(user_list)):
                name = user_list[i]["username"]
                usernames.append(name)

            username = request.form.get("username")
            password = request.form.get("password")
            confirmation = request.form.get("confirmation")

            if (not username) or (username in usernames):
                flash("Invalid username")
                return redirect("/register")

            if (not password or not confirmation) or (confirmation!=password):
                flash("Invalid password")
                return redirect("/register")
            
            password_hash = generate_password_hash(request.form.get("password"), method='pbkdf2:sha256', salt_length=8)
            db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", (request.form.get("username"), password_hash))
            con.commit()
            return redirect("/")
    #display registration page with form
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "POST":
        with sqlite3.connect("finance.db") as con:
            con.row_factory = sqlite3.Row
            db = con.cursor()
            userid = session["user_id"]
            if request.form['sale']=="Sell Stock":

                symbol = request.form.get("symbol")
                def check():
                        
                    db.execute("SELECT * FROM holdings WHERE symbol = ? AND user_id = ?", (symbol, userid))
                    database = db.fetchall()
                    check_symbol = len(database)
                    return check_symbol
                
                final_check = check()
                if final_check==0:
                    flash("You do not own any shares in this company")
                    return redirect("/sell")

                if request.form.get("shares")=="":
                    flash("Please enter a valid # of Shares")
                    return redirect("/sell")
                    

                price = float(lookup(symbol)['price'])
                type_sell = "Sell"
                current_time = datetime.datetime.now()

                db.execute("SELECT * FROM holdings WHERE user_id = ? AND symbol = ?", (userid, symbol))
                stock_rows = db.fetchall()
                current_shares = stock_rows[0]["shares"]
                shares = int(request.form.get("shares"))
                if shares>current_shares:
                    flash(f"Invalid # of Shares: Ensure that you own enough shares of {symbol} to sell")
                    return redirect("/sell")
                else:
                    db.execute("INSERT INTO purchases (user_id, company_name, shares, time, price, type) VALUES(?, ?, ?, ?, ?, ?)", (userid, lookup(symbol)['name'], shares, current_time, price, type_sell))
                    total_shares = current_shares-shares
                    db.execute("UPDATE holdings SET shares = ? WHERE user_id = ? AND symbol = ?", (total_shares, userid, symbol))
                    con.commit()

                    def update_cash():
                        db.execute("SELECT * FROM users WHERE id = ?", (userid,))
                        rows = db.fetchall()
                        cash = rows[0]["cash"]
                        shares = int(request.form.get("shares"))
                        total_sale = price*shares
                        updatedCash = cash + total_sale
                        db.execute("UPDATE users SET cash = ? WHERE id = ?", (updatedCash, userid))
                    update_cash()
                flash('Sale successful!')
                return redirect("/")
            else:
                c_symbol = request.form.get("c_symbol")
                
                def check():
                    db.execute("SELECT * FROM crypto WHERE symbol = ? AND user_id = ?", (c_symbol, userid))
                    database = db.fetchall()
                    check_symbol = len(database)
                    return check_symbol
                
                final_check = check()
                if final_check==0:
                    flash("You do not own anything in this cryptocurrency")
                    return redirect("/sell")

                if request.form.get("amount")=="":
                    flash("Please enter a valid amount")
                    return redirect("/sell")

                price = float(c_lookup(c_symbol)['price'])
                type_sell = "Sell"
                current_time = datetime.datetime.now()

                db.execute("SELECT * FROM crypto WHERE user_id = ? AND symbol = ?", (userid, c_symbol))
                crypto_rows = db.fetchall()
                current_amount = crypto_rows[0]["amount"]
                amount = float(request.form.get("amount"))
                if amount>current_amount:
                    flash("Invalid Amount: Ensure the value is greater than zero and you own enough of the crypto")
                    return redirect("/sell")
                else:
                    db.execute("INSERT INTO purchases (user_id, company_name, shares, time, price, type) VALUES(?, ?, ?, ?, ?, ?)", (userid, c_lookup(c_symbol)['name'], amount, current_time, price, type_sell))
                    total = current_amount-amount
                    db.execute("UPDATE crypto SET amount = ? WHERE user_id = ? AND symbol = ?", (total, userid, c_symbol))
                    con.commit()

                    def update_cash():
                        db.execute("SELECT * FROM users WHERE id = ?", (userid,))
                        rows = db.fetchall()
                        cash = rows[0]["cash"]
                        amount = float(request.form.get("amount"))
                        total_sale = price*amount
                        updatedCash = cash + total_sale
                        db.execute("UPDATE users SET cash = ? WHERE id = ?", (updatedCash, userid))
                    update_cash()
                flash('Sale successful!')
                return redirect("/")
    else:
        return render_template("sell.html")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return flash(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
