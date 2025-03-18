"""
This module takes care of starting the API Server, Loading the DB and Adding the endpoints
"""
import os
import bcrypt
from datetime import timedelta

from utils import APIException, generate_sitemap
from admin import setup_admin

from flask import Flask, request, jsonify
from flask_migrate import Migrate
from flask_swagger import swagger
from flask_cors import CORS
from sqlalchemy import or_

from models import db, Users,Favorites,Films,Planets,People,FavoritesType
from flask_jwt_extended import create_access_token,get_csrf_token,get_jwt_identity,jwt_required,JWTManager,set_access_cookies,unset_jwt_cookies


app = Flask(__name__)
app.url_map.strict_slashes = False

db_url = os.getenv("DATABASE_URL")
if db_url is not None:
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url.replace("postgres://", "postgresql://")
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:////tmp/test.db"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

#JWT
jwt_key = os.getenv("JWT_SECRET_KEY")

app.config["JWT_SECRET_KEY"] = "cO48sKPDnc3cbbnAqwq"  # Change this!
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_CSRF_PROTECT"] = True
app.config["JWT_CSRF_IN_COOKIES"] = True
app.config["JWT_COOKIE_SECURE"] = True
app.config["JWT_ACCESS_COOKIE_NAME"] = "access_token_cookie"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
app.config["JWT_ACCESS_CSRF_HEADER_NAME"] = "X-CSRF-TOKEN" 
jwt = JWTManager(app)

MIGRATE = Migrate(app, db)
db.init_app(app)
app.config['CORS_HEADERS'] = 'Content-Type'
CORS(app,supports_credentials=True)
setup_admin(app)

# Handle/serialize errors like a JSON object
@app.errorhandler(APIException)
def handle_invalid_usage(error):
    return jsonify(error.to_dict()), error.status_code

# generate sitemap with all your endpoints
@app.route('/')
def sitemap():
    return generate_sitemap(app)

tables = {
        "films" : Films,
    "planets" : Planets,
    "people" : People
    }


@app.route('/register',methods=['POST'])
def register():
    data = request.get_json()
    email = data.get("email")
    username = data.get("username")
    password = data.get("password")

    required_fields = ["username","email","password"]
    if not all(field in data for field in required_fields):
        return jsonify({"message":"Missing required fields"}),400
    
    existing_user = db.session.query(Users).filter(or_(Users.username == username,Users.email == email)).first()
    if existing_user:
        return jsonify({"error":"Username or Email already registered"}),400
    
    hashedPassword = bcrypt.hashpw(password.encode('utf-8'),bcrypt.gensalt()).decode('utf-8')

    new_user = Users(email=email,username=username,password=hashedPassword)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message":"User registered successfully"}),201


@app.route('/login', methods=['POST'])
def get_login():
    data = request.get_json()
    username = data["username"]
    password = data["password"]

    required_fields= ["username","password"]

    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return jsonify({"error": "Missing required fields", "missing": missing_fields}), 400
    
    user = Users.query.filter_by(username=username).first()

    if not user:
        return jsonify({"error":"Username not found"}), 400

    is_password_valid = bcrypt.checkpw(password.encode('utf-8'),user.password.encode('utf-8'))

    if not is_password_valid:
        return jsonify({"error":"Password not correct"}), 400

    access_token = create_access_token(identity=str(user.user_id))
    csrf_token = get_csrf_token(access_token)
    response = jsonify({
        "msg": "login successful",
        "user": {
            "id": user.user_id,
            "username": user.username
        },
        "csrf_token": csrf_token
        })
    
    set_access_cookies(response,access_token)
    
    return response

@app.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    user_id = get_jwt_identity()
    user = Users.query.get(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404
    
    response = jsonify({
        "id": user.user_id,
        "username": user.username
    })

    return response,200


@app.route('/logout',methods=['POST'])
@jwt_required()
def logout_with_cookies():
    response= jsonify({"message":"logout successful"})
    unset_jwt_cookies(response)
    return response
    
                                            #GET USERS

@app.route('/users',methods=['GET'])
def get_user():
    users = Users.query.all()
    response_body = {
        "content": users
    }
    return jsonify(response_body),200

                                            # GET,POST & DELETE FAVORITES

@app.route('/favorites', methods=["GET", "POST", "DELETE"])
@jwt_required()
def handle_favorites():
    user_id = get_jwt_identity()
    if request.method == "GET":
        favorites = Favorites.query.filter_by(user_id=user_id).all()
        return jsonify(favorites), 200

    data = request.get_json()

    if request.method == "POST":
        required_fields = ["type_enum","external_id","name"]
    
        if not all(field in data for field in required_fields):
            return jsonify("error: missing required fields"), 400
        if data["type_enum"] not in FavoritesType.__members__:
            return jsonify({"error": "Invalid type_enum. Must be one of valid types"}), 400
        if Favorites.query.filter_by(external_id=data["external_id"],user_id=user_id,type_enum=data["type_enum"]).first():
            return jsonify({"error":"Resources already in favorites"}), 400
        if not tables[data["type_enum"]].query.filter_by(id=data["external_id"]).first():
            return jsonify({"error":"Resource not found"}), 400
        
        new_favorite = Favorites(
            user_id=user_id,
            external_id=data["external_id"],
            name=data["name"],
            type_enum=data["type_enum"]
        )

        db.session.add(new_favorite)
        db.session.commit()
        return jsonify(new_favorite), 200


    if request.method == "DELETE":
        required_fields = ["favorite_id"]
        
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({"error": "Missing required fields", "missing": missing_fields}), 400


        favorite = Favorites.query.filter_by(
            favorite_id=data["favorite_id"],user_id=user_id
        ).first()

        if not favorite:
            return jsonify({"error":"Favorite not found"}), 400
    
        db.session.delete(favorite)
        db.session.commit()

        return jsonify({"message":"Favorite deleted"}), 200

                                            # GET,POST & DELETE FILMS

@app.route('/films',methods=['GET'])
def get_films():
    films_list = Films.query.all()
    response_body = {
        "content": films_list
    }
    return jsonify(response_body),200

@app.route('/films/<int:id>',methods=['GET'])
def get_film(id):
    film = Films.query.get(id)
    response_body = {
        "content": film
    }
    return jsonify(response_body),200

@app.route('/films',methods=['POST'])
def post_film():
    data = request.get_json(force=True)
    required_fields = ["title","episode","release_date","director","producer"]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return ({"message":"error","missing fields" : missing_fields}),400

    new_film = Films(
        name=data["name"],
        episode=data["episode"],
        release_date=data["release_date"],
        opening_crawl=data["opening_crawl"],
        director=data["director"],
        producer=data["producer"],
    )
    db.session.add(new_film)
    db.session.commit()
    return jsonify(new_film),200

@app.route('/films/<int:id>',methods=['DELETE'])
def delete_film(id):
    film = Films.query.get(id)
    if not film:
        return jsonify({"message":"No film found with the requested id"}),400

    db.session.delete(film)
    db.session.commit()

    return jsonify({"message": "Film deleted successfully"}),200

                                         # GET,POST & DELETE PLANETS

@app.route('/planets',methods=['GET'])
def get_planets():
    planets_list = Planets.query.all()
    response_body = {
        "content": planets_list
    }
    return jsonify(response_body),200

@app.route('/planets/<int:id>',methods=['GET'])
def get_planet(id):
    planet = Planets.query.get(id)
    response_body = {
        "content": planet
    }
    return jsonify(response_body),200   

@app.route('/planets',methods=['POST'])
def post_planet():
    data = request.get_json(force=True)
    required_fields = ["name","population","climate","diameter","gravity"]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return ({"message":"error","missing fields" : missing_fields}),400

    new_planet = Planets(
        name=data["name"],
        population=data["population"],
        climate=data["climate"],
        diameter=data["diameter"],
        gravity=data["gravity"],
    )
    db.session.add(new_planet)
    db.session.commit()
    return jsonify(new_planet),200

@app.route('/planets/<int:id>',methods=['DELETE'])
def delete_planet(id):
    planet = Planets.query.get(id)
    if not planet:
        return jsonify({"message":"No planet found with the requested id"}),400

    db.session.delete(planet)
    db.session.commit()

    return jsonify({"message": "Planet deleted successfully"}),200


                                            # GET,POST & DELETE PEOPLE
@app.route('/people',methods=['GET'])
def get_people():
    people_list = People.query.all()
    response_body = {
        "content": people_list
    }

    return jsonify(response_body),200

@app.route('/people/<int:id>',methods=['GET'])
def get_person(id):
    person = People.query.get(id)
    response_body = {
        "content": person
    }
    return jsonify(response_body),200   

@app.route('/people',methods=['POST'])
def post_person():
    data = request.get_json(force=True)
    required_fields = ["name","species","skin_color","hair_color","height","homeworld"]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return ({"message":"error","missing fields" : missing_fields}),400

    new_person = People(
        name=data["name"],
        species=data["species"],
        skin_color=data["skin_color"],
        hair_color=data["hair_color"],
        height=data["height"],
        homeworld=data["homeworld"]
    )
    db.session.add(new_person)
    db.session.commit()
    return jsonify(new_person),200

@app.route('/person/<int:id>',methods=['DELETE'])
def delete_person(id):
    person = People.query.get(id)
    if not person:
        return jsonify({"message":"No person found with the requested id"}),400

    db.session.delete(person)
    db.session.commit()

    return jsonify({"message": "Person deleted successfully"}),200

# this only runs if `$ python src/app.py` is executed
if __name__ == '__main__':
    PORT = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=PORT, debug=False)