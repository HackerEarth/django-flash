from django.db import models


class ModelA(models.Model):
    num = models.IntegerField()
    text = models.CharField(max_length=50)


class ModelB(models.Model):
    num = models.IntegerField()
    text = models.CharField(max_length=50)
    a = models.ForeignKey(ModelA, on_delete=models.CASCADE)


class ModelC(models.Model):
    a = models.ForeignKey(ModelA, on_delete=models.CASCADE)
    b = models.ForeignKey(ModelB, on_delete=models.CASCADE)
    num = models.IntegerField()


class ModelD(models.Model):
    a_list = models.ManyToManyField(ModelA)
    num = models.IntegerField()
