from werkzeug.security import generate_password_hash
generate_password_hash("Pedrinche@2020")
print("la contraseña hash es: ", generate_password_hash("Pedrinche@2020"))