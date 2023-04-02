from PIL import Image
from fastapi import FastAPI, Depends, File, Form, UploadFile, HTTPException
from tensorflow import keras
import io
import numpy as np
import config
from error import ModelNotAvailableError
import database
from datetime import datetime

class Analyzer:
    def __init__(self):
        self.models: dict = {}

    def load_all_models(self):
        # loop through all the models setup in config
        for model in config.MODELS:
            new_model = PredictionModel()
            new_model.load_model(config.MODELS[model])
            new_model.labels = config.LABELS[model]
            self.models[model] = new_model

    
class PredictionModel:
    def __init__(self):
        self.model = None
        self.labels = None

    def load_model(self, path_to_model: str):
        self.model = keras.models.load_model(path_to_model)
        print(f"Succesefully loaded model from {path_to_model}")
        
    def predict(self, data):
        if not self.model:
            raise ModelNotAvailableError
        return self.model.predict(data)
    
    
app = FastAPI()

analyzer = Analyzer()
analyzer.load_all_models()
def get_analyzer():
    return analyzer

db = database.Database()
def get_db():
    return db

@app.get("/")
async def root():
    return {"message": "Server health page - running"}

@app.get("/test_db")
async def test_db(db: database.Database = Depends(get_db)):
    plants = db.query_all_plants()
    if not plants:
        raise HTTPException(status_code=404, detail="No disease available in database")
    return [{f"plant": plant.name} for plant in plants]


@app.post("/api/v1/uploadfile")
async def analyze_images(analyzer: Analyzer = Depends(get_analyzer), image1: UploadFile = File(...), image2: UploadFile = File(...), plant: str = Form(...)):
    if plant not in analyzer.models.keys():
        raise HTTPException(status_code=500, detail="No model available for the provided plant")
    
    # select proper model for the requested plant and get the input dimensions to fit model's input layer
    pred_model = analyzer.models[plant]
    dimensions = pred_model.model.layers[0].input_shape[1:3]
    print(dimensions)
    
    if type(dimensions) is not tuple:
        raise HTTPException(status_code=500, detail="Model dimensions are not supported")
    if len(dimensions) != 2:
        raise HTTPException(status_code=500, detail="Model dimensions are not supported")
    
    contents1 = await image1.read()
    img1 = Image.open(io.BytesIO(contents1))
    contents2 = await image2.read()
    img2 = Image.open(io.BytesIO(contents2))
    
    # collect the image to enlarge dataset
    if config.COLLECTION_ENABLED:
        try:
            file_name = datetime.now().strftime('%Y_%m_%d-%I_%M_%S')
            img1.save(f"{config.COLLECTION_PATH}/{file_name}-1.jpg")
            img2.save(f"{config.COLLECTION_PATH}/{file_name}-2.jpg")
        except:
            print("Failed to save images")

    # resize the image to input dimensions of the model
    img1 = img1.resize(dimensions)
    img2 = img2.resize(dimensions)
    
    # Convert images to RGB mode to remove the alpha channel if present
    # for example: user sends a PNG image with transparency
    img1 = img1.convert('RGB')
    img2 = img2.convert('RGB')
    
    # Convert image to numpy array
    np_array1 = np.array(img1)
    np_array2 = np.array(img2)

    # normalize the values
    # np_array = np_array / 255.0
    
    # add extra dimension to create a batch of size 1
    input_batch1 = np.expand_dims(np_array1, axis=0)
    input_batch2 = np.expand_dims(np_array2, axis=0)

    # gather predictions from both models
    predictions1 = pred_model.predict(input_batch1)
    predictions2 = pred_model.predict(input_batch2)
    
    # concat the results and find max value for each pair
    predictions_concat = np.concatenate((predictions1.reshape(-1, 1), predictions2.reshape(-1, 1)), axis=1)
    predictions = np.amax(predictions_concat, axis=1)
    
    # use softmax function on the concatenated predictions
    # predictions = np.exp(predictions) / np.sum(np.exp(predictions), axis=0)

    # adjust the weights of the predictions to add up to 1 (100%)
    predictions = predictions / np.sum(predictions)

    # create a list of dictionaries with the results and return top 5 predictions
    predictions_array = [{"name": pred_model.labels[i], "percentage": float(predictions[i])} for i in range(len(pred_model.labels))]
    predictions_array.sort(key=lambda x: x["percentage"], reverse=True)
    top_predictions = predictions_array[:5]
    return top_predictions


@app.post("/api/v1/disease_detail")
async def disease_detail(disease_name: str = Form(...), plant_name: str = Form(...), database: database.Database = Depends(get_db)):
    disease_summary = db.query_disease_detail_specify_plant(disease_name=disease_name, plant_name=plant_name)
    if not disease_summary:
        raise HTTPException(status_code=404, detail="Disease not found")
    return disease_summary


@app.post("/api/v1/disease_list")
async def disease_list(plant_name: str = Form(...), database: database.Database = Depends(get_db)):
    disease_list = db.query_all_diseases_for_plant(plant_name=plant_name)
    if not disease_list:
        return
    return disease_list

@app.get("/api/v1/plant_list")
async def plant_list():
    plant_list = db.query_all_plants()
    if not plant_list:
        raise HTTPException(status_code=404, detail="No plants found")
    return plant_list

@app.get("/api/v1/news_list")
async def news_list():
    news_list = db.query_all_news()
    if not news_list:
        raise HTTPException(status_code=404, detail="No news found")
    return news_list


if __name__ == "__main__":
    import uvicorn
    #analyzer = Analyzer()
    #analyzer.load_all_models()
    uvicorn.run(app, host="localhost", port=8000)
