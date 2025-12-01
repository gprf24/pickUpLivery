Starting the server:

docker compose build --no-cache web

docker compose up -d



On AWS:
cd ~/pickuplivery
docker build -t pickuplivery:latest .
 
docker run -d -p 8000:80 pickuplivery:latest
docker ps
curl http://localhost:8000
~/projects/pickuplivery
 
 
cd ~/projects/pickuplivery
git pull origin main
 
docker-compose down
docker-compose up -d --build
docker ps
curl http://localhost:8000