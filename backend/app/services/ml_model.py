import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
import os

MODEL_PATH = "models/breast_cancer_model.h5"  # Asegúrate de tener el modelo aquí

class BreastCancerModel:
    def __init__(self):
        self.model = load_model(MODEL_PATH)

    def predict(self, image_path):
        img = image.load_img(image_path, target_size=(224, 224))
        img_array = image.img_to_array(img)
        img_array = np.expand_dims(img_array, axis=0) / 255.0
        prediction = self.model.predict(img_array)
        class_idx = np.argmax(prediction)
        classes = ["benign", "malignant"]
        return classes[class_idx], float(prediction[0][class_idx])
