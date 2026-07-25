-- MySQL dump 10.13  Distrib 9.7.1, for Linux (x86_64)
--
-- Host: localhost    Database: neongelion
-- ------------------------------------------------------
-- Server version	9.7.1

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `admin_action_holds`
--

DROP TABLE IF EXISTS `admin_action_holds`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `admin_action_holds` (
  `id` int NOT NULL AUTO_INCREMENT,
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `actor_id` bigint NOT NULL,
  `action_type` enum('mute','ban') NOT NULL,
  `rights_json` text NOT NULL,
  `custom_title` varchar(32) DEFAULT NULL,
  `until` datetime DEFAULT NULL,
  `reason` varchar(500) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_admin_hold` (`chat_id`,`user_id`),
  KEY `idx_admin_holds_until` (`until`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `admin_action_holds`
--

LOCK TABLES `admin_action_holds` WRITE;
/*!40000 ALTER TABLE `admin_action_holds` DISABLE KEYS */;
/*!40000 ALTER TABLE `admin_action_holds` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `admins`
--

DROP TABLE IF EXISTS `admins`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `admins` (
  `user_id` bigint NOT NULL,
  `level` tinyint NOT NULL DEFAULT '1',
  `added_by` bigint DEFAULT NULL,
  `added_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `admins`
--

LOCK TABLES `admins` WRITE;
/*!40000 ALTER TABLE `admins` DISABLE KEYS */;
INSERT INTO `admins` VALUES (5242991121,2,7790517846,'2026-07-12 15:35:00'),(5707066924,3,8114583471,'2026-07-12 14:45:14'),(7547410082,2,7790517846,'2026-07-13 08:14:06'),(8407034059,3,8114583471,'2026-07-14 11:21:57'),(8759004874,1,7790517846,'2026-07-13 08:11:43');
/*!40000 ALTER TABLE `admins` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `bans`
--

DROP TABLE IF EXISTS `bans`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `bans` (
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `banned_by` bigint NOT NULL,
  `reason` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_id`,`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `bans`
--

LOCK TABLES `bans` WRITE;
/*!40000 ALTER TABLE `bans` DISABLE KEYS */;
/*!40000 ALTER TABLE `bans` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `bot_data`
--

DROP TABLE IF EXISTS `bot_data`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `bot_data` (
  `data_key` varchar(191) NOT NULL,
  `data_value` text,
  `updated_by` bigint DEFAULT NULL,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`data_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `bot_data`
--

LOCK TABLES `bot_data` WRITE;
/*!40000 ALTER TABLE `bot_data` DISABLE KEYS */;
INSERT INTO `bot_data` VALUES ('norm:-1003673552861','100',8114583471,'2026-07-13 22:02:15');
/*!40000 ALTER TABLE `bot_data` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `call_signs`
--

DROP TABLE IF EXISTS `call_signs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `call_signs` (
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `emoji` varchar(16) NOT NULL,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_id`,`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `call_signs`
--

LOCK TABLES `call_signs` WRITE;
/*!40000 ALTER TABLE `call_signs` DISABLE KEYS */;
INSERT INTO `call_signs` VALUES (-1003811995090,5242991121,'🪡','2026-07-13 11:25:54'),(-1003811995090,5707066924,'🐼','2026-07-13 11:22:06'),(-1003811995090,7547410082,'🦊','2026-07-13 11:27:12'),(-1003811995090,7790517846,'🐯','2026-07-13 11:22:05'),(-1003811995090,8114583471,'👨‍🦽','2026-07-13 11:25:29'),(-1003811995090,8407034059,'🐢','2026-07-13 11:22:06'),(-1003811995090,8759004874,'🎯','2026-07-13 11:22:06'),(-1003673552861,1307190691,'🐰','2026-07-16 14:53:16'),(-1003673552861,1312624847,'🦁','2026-07-15 18:31:15'),(-1003673552861,1475524466,'🌙','2026-07-13 16:45:40'),(-1003673552861,1508737016,'🐙','2026-07-14 03:12:39'),(-1003673552861,1984456868,'🌊','2026-07-13 11:40:23'),(-1003673552861,5080664830,'🍉','2026-07-13 11:40:23'),(-1003673552861,5238563460,'🌟','2026-07-13 20:52:39'),(-1003673552861,5242991121,'🐶','2026-07-13 11:40:21'),(-1003673552861,5248704461,'🔥','2026-07-13 11:40:23'),(-1003673552861,5707066924,'🔥','2026-07-13 11:50:43'),(-1003673552861,5771975148,'🌊','2026-07-13 11:40:22'),(-1003673552861,5918411165,'🐨','2026-07-15 18:31:15'),(-1003673552861,6105651374,'🐔','2026-07-13 11:40:23'),(-1003673552861,6542960747,'☀️','2026-07-13 11:40:22'),(-1003673552861,6723156345,'🍀','2026-07-14 03:12:39'),(-1003673552861,7329106105,'🍀','2026-07-15 18:31:15'),(-1003673552861,7547410082,'🦊','2026-07-13 11:40:21'),(-1003673552861,7579895039,'👾','2026-07-13 11:40:23'),(-1003673552861,7790517846,'🐯','2026-07-15 18:31:15'),(-1003673552861,7982777490,'🐷','2026-07-13 11:40:22'),(-1003673552861,8037189102,'❄️','2026-07-13 11:40:23'),(-1003673552861,8114583471,'👨‍🦽','2026-07-13 11:50:27'),(-1003673552861,8149834084,'🐼','2026-07-13 11:40:22'),(-1003673552861,8176377509,'🍒','2026-07-15 19:28:30'),(-1003673552861,8265845625,'🍀','2026-07-16 14:53:16'),(-1003673552861,8288451562,'🦊','2026-07-13 11:40:22'),(-1003673552861,8407034059,'🐢','2026-07-13 11:40:21'),(-1003673552861,8509346376,'🐙','2026-07-13 19:50:55'),(-1003673552861,8650988494,'🐔','2026-07-13 11:40:22'),(-1003673552861,8700500174,'🐔','2026-07-13 11:40:21'),(-1003673552861,8759004874,'🪖','2026-07-13 11:52:09');
/*!40000 ALTER TABLE `call_signs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `call_unregs`
--

DROP TABLE IF EXISTS `call_unregs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `call_unregs` (
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `message` varchar(256) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_id`,`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `call_unregs`
--

LOCK TABLES `call_unregs` WRITE;
/*!40000 ALTER TABLE `call_unregs` DISABLE KEYS */;
/*!40000 ALTER TABLE `call_unregs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `chat_roles`
--

DROP TABLE IF EXISTS `chat_roles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `chat_roles` (
  `id` int NOT NULL AUTO_INCREMENT,
  `chat_id` bigint NOT NULL,
  `name` varchar(64) NOT NULL,
  `category` varchar(64) DEFAULT NULL,
  `status` enum('free','taken','reserved') NOT NULL DEFAULT 'free',
  `holder_user_id` bigint DEFAULT NULL,
  `reserved_user_id` bigint DEFAULT NULL,
  `reserved_at` datetime DEFAULT NULL,
  `proposed_by` bigint DEFAULT NULL,
  `approved` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_chat_role_name` (`chat_id`,`name`),
  KEY `idx_roles_chat_status` (`chat_id`,`status`),
  KEY `idx_roles_holder` (`chat_id`,`holder_user_id`),
  KEY `idx_roles_reserved` (`chat_id`,`reserved_user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=329 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `chat_roles`
--

LOCK TABLES `chat_roles` WRITE;
/*!40000 ALTER TABLE `chat_roles` DISABLE KEYS */;
INSERT INTO `chat_roles` VALUES (1,-1004315708356,'Хуйло',NULL,'free',NULL,NULL,NULL,8114583471,0,'2026-07-14 11:29:37'),(2,-1003811995090,'Синдзи Икари','Основные','taken',8759004874,NULL,NULL,NULL,1,'2026-07-14 11:39:25'),(3,-1003811995090,'Рей Аянами','Основные','taken',7547410082,NULL,NULL,NULL,1,'2026-07-14 11:39:25'),(4,-1003811995090,'Сорью Аска','Основные','taken',5242991121,NULL,NULL,NULL,1,'2026-07-14 11:39:25'),(5,-1003811995090,'Тодзи Судзухара','Основные','taken',1475524466,NULL,NULL,NULL,1,'2026-07-14 11:39:25'),(6,-1003811995090,'Каору Нагиса','Основные','taken',7790517846,NULL,NULL,NULL,1,'2026-07-14 11:39:26'),(7,-1003811995090,'Гендо Икари','Сотрудники NERV','taken',6881601407,NULL,NULL,NULL,1,'2026-07-14 11:39:26'),(8,-1003811995090,'Кодзо Фуюцуки','Сотрудники NERV','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:26'),(9,-1003811995090,'Мисато Кацураги','Сотрудники NERV','taken',8700500174,NULL,NULL,NULL,1,'2026-07-14 11:39:26'),(10,-1003811995090,'Рицуко Акаги','Сотрудники NERV','taken',8670492812,NULL,NULL,NULL,1,'2026-07-14 11:39:26'),(11,-1003811995090,'Редзи Кадзи','Сотрудники NERV','taken',8037189102,NULL,NULL,NULL,1,'2026-07-14 11:39:26'),(12,-1003811995090,'Майя Ибуки','Сотрудники NERV','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:27'),(13,-1003811995090,'Макото Хюга','Сотрудники NERV','taken',8149834084,NULL,NULL,NULL,1,'2026-07-14 11:39:27'),(14,-1003811995090,'Сигару Аоба','Сотрудники NERV','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:27'),(15,-1003811995090,'Наоко Акаги','Сотрудники NERV','taken',6105651374,NULL,NULL,NULL,1,'2026-07-14 11:39:27'),(16,-1003811995090,'Юи Икари','Сотрудники NERV','taken',5771975148,NULL,NULL,NULL,1,'2026-07-14 11:39:27'),(17,-1003811995090,'Кеко Цеппелин','Сотрудники NERV','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:27'),(18,-1003811995090,'Доктор Кацураги','Сотрудники NERV','taken',7579895039,NULL,NULL,NULL,1,'2026-07-14 11:39:27'),(19,-1003811995090,'Кэнсукэ Аида','Одноклассники, жители Токио-3','taken',8176377509,NULL,NULL,NULL,1,'2026-07-14 11:39:28'),(20,-1003811995090,'Хикари Хораки','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:28'),(21,-1003811995090,'Кодама Хораки','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:28'),(22,-1003811995090,'Ноцуко Хораки','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:28'),(23,-1003811995090,'Пен Пен','Одноклассники, жители Токио-3','taken',5080664830,NULL,NULL,NULL,1,'2026-07-14 11:39:28'),(24,-1003811995090,'Киил Лоренц','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:28'),(25,-1003811995090,'Сиро Токита','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:28'),(26,-1003811995090,'Кейл Лоренц','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:29'),(27,-1003811995090,'Кихель Лоренц','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:29'),(28,-1003811995090,'Исрафель','Ангелы','taken',1508737016,NULL,NULL,NULL,1,'2026-07-14 11:39:29'),(29,-1003811995090,'Сандальфон','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:29'),(30,-1003811995090,'Матариэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:29'),(31,-1003811995090,'Рамиил','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:29'),(32,-1003811995090,'Сахакуиль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:29'),(33,-1003811995090,'Иреуль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:30'),(34,-1003811995090,'Лелиэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:30'),(35,-1003811995090,'Бардиэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:30'),(36,-1003811995090,'Зеруэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:30'),(37,-1003811995090,'Араэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:30'),(38,-1003811995090,'Армисаэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:30'),(39,-1003811995090,'Лилин','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:31'),(40,-1003811995090,'Лилит','Ангелы','taken',6723156345,NULL,NULL,NULL,1,'2026-07-14 11:39:31'),(41,-1003811995090,'Адам','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:31'),(42,-1003811995090,'Мари Макинами','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:31'),(43,-1003811995090,'Аска Сикинами','Восстановление Евангелиона','taken',7982777490,NULL,NULL,NULL,1,'2026-07-14 11:39:31'),(44,-1003811995090,'Сакура Судзухара','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:31'),(45,-1003811995090,'Коудзи Такао','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:31'),(46,-1003811995090,'Хидэки Тама','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:32'),(47,-1003811995090,'Сумирэ Нагара','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:32'),(48,-1003811995090,'Мидори Китаками','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:32'),(49,-1003811995090,'Ева-00','Евангелионы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:32'),(50,-1003811995090,'Ева-01','Евангелионы','taken',8509346376,NULL,NULL,NULL,1,'2026-07-14 11:39:32'),(51,-1003811995090,'Ева-02','Евангелионы','taken',5707066924,NULL,NULL,NULL,1,'2026-07-14 11:39:32'),(52,-1003811995090,'Ева-03','Евангелионы','taken',6542960747,NULL,NULL,NULL,1,'2026-07-14 11:39:33'),(53,-1003811995090,'Ева-04','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:33'),(54,-1003811995090,'Ева-05','Евангелионы','taken',5238563460,NULL,NULL,NULL,1,'2026-07-14 11:39:33'),(55,-1003811995090,'Ева-06','Евангелионы','taken',5918411165,NULL,NULL,NULL,1,'2026-07-14 11:39:33'),(56,-1003811995090,'Ева-07','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:33'),(57,-1003811995090,'Ева-08','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:33'),(58,-1003811995090,'Ева-09','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:33'),(59,-1003811995090,'Ева-13','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:34'),(60,-1003811995090,'Мина-тян','Дополнительно','taken',1984456868,NULL,NULL,NULL,1,'2026-07-14 11:39:34'),(61,-1003811995090,'Копье Лонгина','Дополнительно','taken',8114583471,NULL,NULL,NULL,1,'2026-07-14 11:39:34'),(62,-1003811995090,'Копье Кассиуса','Дополнительно','taken',6516227864,NULL,NULL,NULL,1,'2026-07-14 11:39:34'),(63,-1003811995090,'Пиво Мисато','Дополнительно','taken',7329106105,NULL,NULL,NULL,1,'2026-07-14 11:39:34'),(64,-1003811995090,'Арбуз','Дополнительно','taken',8288451562,NULL,NULL,NULL,1,'2026-07-14 11:39:34'),(65,-1003811995090,'Фанта Рей','Дополнительно','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:39:34'),(66,-1003811995090,'Сперма Синдзи','Дополнительно','taken',5400209637,NULL,NULL,NULL,1,'2026-07-14 11:39:35'),(67,-1003673552861,'Синдзи Икари','Основные','taken',8759004874,NULL,NULL,NULL,1,'2026-07-14 11:41:23'),(68,-1003673552861,'Рей Аянами','Основные','taken',7547410082,NULL,NULL,NULL,1,'2026-07-14 11:41:24'),(69,-1003673552861,'Сорью Аска','Основные','taken',5242991121,NULL,NULL,NULL,1,'2026-07-14 11:41:24'),(70,-1003673552861,'Тодзи Судзухара','Основные','taken',1475524466,NULL,NULL,NULL,1,'2026-07-14 11:41:24'),(73,-1003673552861,'Кодзо Фуюцуки','Сотрудники NERV','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:24'),(74,-1003673552861,'Мисато Кацураги','Сотрудники NERV','taken',8700500174,NULL,NULL,NULL,1,'2026-07-14 11:41:24'),(75,-1003673552861,'Рицуко Акаги','Сотрудники NERV','taken',8670492812,NULL,NULL,NULL,1,'2026-07-14 11:41:25'),(76,-1003673552861,'Редзи Кадзи','Сотрудники NERV','taken',8037189102,NULL,NULL,NULL,1,'2026-07-14 11:41:25'),(77,-1003673552861,'Майя Ибуки','Сотрудники NERV','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:25'),(78,-1003673552861,'Макото Хюга','Сотрудники NERV','taken',8149834084,NULL,NULL,NULL,1,'2026-07-14 11:41:25'),(79,-1003673552861,'Сигару Аоба','Сотрудники NERV','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:25'),(80,-1003673552861,'Наоко Акаги','Сотрудники NERV','taken',6105651374,NULL,NULL,NULL,1,'2026-07-14 11:41:25'),(81,-1003673552861,'Юи Икари','Сотрудники NERV','taken',5771975148,NULL,NULL,NULL,1,'2026-07-14 11:41:25'),(82,-1003673552861,'Кеко Цеппелин','Сотрудники NERV','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:26'),(83,-1003673552861,'Доктор Кацураги','Сотрудники NERV','taken',7579895039,NULL,NULL,NULL,1,'2026-07-14 11:41:26'),(84,-1003673552861,'Кэнсукэ Аида','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:26'),(85,-1003673552861,'Хикари Хораки','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:26'),(86,-1003673552861,'Кодама Хораки','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:26'),(87,-1003673552861,'Ноцуко Хораки','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:26'),(88,-1003673552861,'Пен Пен','Одноклассники, жители Токио-3','taken',5080664830,NULL,NULL,NULL,1,'2026-07-14 11:41:26'),(89,-1003673552861,'Киил Лоренц','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:26'),(90,-1003673552861,'Сиро Токита','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:27'),(91,-1003673552861,'Кейл Лоренц','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:27'),(92,-1003673552861,'Кихель Лоренц','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:27'),(93,-1003673552861,'Исрафель','Ангелы','taken',1508737016,NULL,NULL,NULL,1,'2026-07-14 11:41:27'),(94,-1003673552861,'Сандальфон','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:27'),(95,-1003673552861,'Матариэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:27'),(96,-1003673552861,'Рамиил','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:28'),(97,-1003673552861,'Сахакуиль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:28'),(98,-1003673552861,'Иреуль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:28'),(99,-1003673552861,'Лелиэль','Ангелы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:28'),(100,-1003673552861,'Бардиэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:28'),(101,-1003673552861,'Зеруэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:28'),(102,-1003673552861,'Араэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:29'),(103,-1003673552861,'Армисаэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:29'),(104,-1003673552861,'Лилин','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:29'),(105,-1003673552861,'Лилит','Ангелы','taken',6723156345,NULL,NULL,NULL,1,'2026-07-14 11:41:29'),(106,-1003673552861,'Адам','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:29'),(107,-1003673552861,'Мари Макинами','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:29'),(108,-1003673552861,'Аска Сикинами','Восстановление Евангелиона','taken',7982777490,NULL,NULL,NULL,1,'2026-07-14 11:41:29'),(109,-1003673552861,'Сакура Судзухара','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:30'),(110,-1003673552861,'Коудзи Такао','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:30'),(111,-1003673552861,'Хидэки Тама','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:30'),(112,-1003673552861,'Сумирэ Нагара','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:30'),(113,-1003673552861,'Мидори Китаками','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:30'),(114,-1003673552861,'Ева-00','Евангелионы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:30'),(115,-1003673552861,'Ева-01','Евангелионы','taken',8509346376,NULL,NULL,NULL,1,'2026-07-14 11:41:30'),(116,-1003673552861,'Ева-02','Евангелионы','taken',5707066924,NULL,NULL,NULL,1,'2026-07-14 11:41:31'),(117,-1003673552861,'Ева-03','Евангелионы','taken',6542960747,NULL,NULL,NULL,1,'2026-07-14 11:41:31'),(118,-1003673552861,'Ева-04','Евангелионы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:31'),(119,-1003673552861,'Ева-05','Евангелионы','taken',5238563460,NULL,NULL,NULL,1,'2026-07-14 11:41:31'),(120,-1003673552861,'Ева-06','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:31'),(121,-1003673552861,'Ева-07','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:31'),(122,-1003673552861,'Ева-08','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:32'),(123,-1003673552861,'Ева-09','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:32'),(124,-1003673552861,'Ева-13','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:32'),(125,-1003673552861,'Мина-тян','Дополнительно','taken',1984456868,NULL,NULL,NULL,1,'2026-07-14 11:41:32'),(126,-1003673552861,'Копье Лонгина','Дополнительно','taken',8114583471,NULL,NULL,NULL,1,'2026-07-14 11:41:32'),(127,-1003673552861,'Копье Кассиуса','Дополнительно','taken',6516227864,NULL,NULL,NULL,1,'2026-07-14 11:41:33'),(128,-1003673552861,'Пиво Мисато','Дополнительно','taken',7329106105,NULL,NULL,NULL,1,'2026-07-14 11:41:33'),(129,-1003673552861,'Арбуз','Дополнительно','taken',8288451562,NULL,NULL,NULL,1,'2026-07-14 11:41:33'),(130,-1003673552861,'Фанта Рей','Дополнительно','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 11:41:33'),(131,-1003673552861,'Сперма Синдзи','Дополнительно','taken',5400209637,NULL,NULL,NULL,1,'2026-07-14 11:41:33'),(262,-1004315708356,'Синдзи Икари','Основные','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:19'),(263,-1004315708356,'Рей Аянами','Основные','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:19'),(264,-1004315708356,'Сорью Аска','Основные','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:19'),(265,-1004315708356,'Тодзи Судзухара','Основные','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:19'),(266,-1004315708356,'Каору Нагиса','Основные','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:19'),(267,-1004315708356,'Гендо Икари','Сотрудники NERV','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:20'),(268,-1004315708356,'Кодзо Фуюцуки','Сотрудники NERV','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:20'),(269,-1004315708356,'Мисато Кацураги','Сотрудники NERV','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:20'),(270,-1004315708356,'Рицуко Акаги','Сотрудники NERV','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:20'),(271,-1004315708356,'Редзи Кадзи','Сотрудники NERV','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:20'),(272,-1004315708356,'Майя Ибуки','Сотрудники NERV','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:20'),(273,-1004315708356,'Макото Хюга','Сотрудники NERV','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:21'),(274,-1004315708356,'Сигару Аоба','Сотрудники NERV','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:21'),(275,-1004315708356,'Наоко Акаги','Сотрудники NERV','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:21'),(276,-1004315708356,'Юи Икари','Сотрудники NERV','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:21'),(277,-1004315708356,'Кеко Цеппелин','Сотрудники NERV','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:21'),(278,-1004315708356,'Доктор Кацураги','Сотрудники NERV','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:21'),(279,-1004315708356,'Кэнсукэ Аида','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:22'),(280,-1004315708356,'Хикари Хораки','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:22'),(281,-1004315708356,'Кодама Хораки','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:22'),(282,-1004315708356,'Ноцуко Хораки','Одноклассники, жители Токио-3','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:22'),(283,-1004315708356,'Пен Пен','Одноклассники, жители Токио-3','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:22'),(284,-1004315708356,'Киил Лоренц','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:22'),(285,-1004315708356,'Сиро Токита','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:22'),(286,-1004315708356,'Кейл Лоренц','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:23'),(287,-1004315708356,'Кихель Лоренц','SEELE, правительство','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:23'),(288,-1004315708356,'Исрафель','Ангелы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:23'),(289,-1004315708356,'Сандальфон','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:23'),(290,-1004315708356,'Матариэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:23'),(291,-1004315708356,'Рамиил','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:23'),(292,-1004315708356,'Сахакуиль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:23'),(293,-1004315708356,'Иреуль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:24'),(294,-1004315708356,'Лелиэль','Ангелы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:24'),(295,-1004315708356,'Бардиэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:24'),(296,-1004315708356,'Зеруэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:24'),(297,-1004315708356,'Араэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:24'),(298,-1004315708356,'Армисаэль','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:24'),(299,-1004315708356,'Лилин','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:25'),(300,-1004315708356,'Лилит','Ангелы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:25'),(301,-1004315708356,'Адам','Ангелы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:25'),(302,-1004315708356,'Мари Макинами','Восстановление Евангелиона','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:25'),(303,-1004315708356,'Аска Сикинами','Восстановление Евангелиона','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:25'),(304,-1004315708356,'Сакура Судзухара','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:25'),(305,-1004315708356,'Коудзи Такао','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:25'),(306,-1004315708356,'Хидэки Тама','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:26'),(307,-1004315708356,'Сумирэ Нагара','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:26'),(308,-1004315708356,'Мидори Китаками','Восстановление Евангелиона','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:26'),(309,-1004315708356,'Ева-00','Евангелионы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:26'),(310,-1004315708356,'Ева-01','Евангелионы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:26'),(311,-1004315708356,'Ева-02','Евангелионы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:27'),(312,-1004315708356,'Ева-03','Евангелионы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:27'),(313,-1004315708356,'Ева-04','Евангелионы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:27'),(314,-1004315708356,'Ева-05','Евангелионы','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:27'),(315,-1004315708356,'Ева-06','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:27'),(316,-1004315708356,'Ева-07','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:27'),(317,-1004315708356,'Ева-08','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:27'),(318,-1004315708356,'Ева-09','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:28'),(319,-1004315708356,'Ева-13','Евангелионы','free',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:28'),(320,-1004315708356,'Мина-тян','Дополнительно','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:28'),(321,-1004315708356,'Копье Лонгина','Дополнительно','taken',8114583471,NULL,NULL,NULL,1,'2026-07-14 12:11:28'),(322,-1004315708356,'Копье Кассиуса','Дополнительно','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:28'),(323,-1004315708356,'Пиво Мисато','Дополнительно','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:29'),(324,-1004315708356,'Арбуз','Дополнительно','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:29'),(325,-1004315708356,'Фанта Рей','Дополнительно','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:29'),(326,-1004315708356,'Сперма Синдзи','Дополнительно','taken',NULL,NULL,NULL,NULL,1,'2026-07-14 12:11:29'),(327,-1003673552861,'Аска',NULL,'free',NULL,NULL,NULL,8114583471,0,'2026-07-14 13:05:32'),(328,-1003811995090,'Рей-q',NULL,'taken',1312624847,NULL,NULL,8114583471,1,'2026-07-15 18:34:09');
/*!40000 ALTER TABLE `chat_roles` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `chat_rules`
--

DROP TABLE IF EXISTS `chat_rules`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `chat_rules` (
  `chat_id` bigint NOT NULL,
  `rules_text` text NOT NULL,
  `updated_by` bigint DEFAULT NULL,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `chat_rules`
--

LOCK TABLES `chat_rules` WRITE;
/*!40000 ALTER TABLE `chat_rules` DISABLE KEYS */;
INSERT INTO `chat_rules` VALUES (-1003673552861,'общие нормы и уважение к участникам\n\n1.1 запрещенные темы: не обсуждаем политику, религию, а также любые расовые, половые и другие различия в негативном ключе. важно уважать чужие границы\n\nнаказание:\n- устное замечание\n- предупреждение (варн) на месяц\n1.2 личные границы\n\nесли кто-то просит прекратить шутку или тему, которая ему неприятна, вы обязаны остановиться. чувствуете давление? сообщите администратору\n\n1.3 кибербуллинг и оскорбления\n\nоскорбления могут быть допустимы только в шуточной форме. но если вам неприятно - скажите человеку сразу. молчание = согласие на продолжение\n\nнаказание:\n- устное замечание\n- предупреждение (варн)\n\n1.4 разжигание конфликтов\nне провоцируйте ссоры. если вас пытаются взбесить - говорите админам\n- предупреждение (варн) на месяц \n\n2. порядок действий в конфликтных ситуациях\n2.1 как пожаловаться: если вам или другим стало дискомфортно из-за участника, направьте жалобу администрации. кратко опишите ситуацию и укажите конкретные сообщения. каждую жалобу рассмотрят\n\n- в случае около 3 жалоб администратор проведет беседу или сразу удалит участника.\n\n3. активность и чистки (каждую пятницу в любое время)\n\n3.1 норма сообщений:\n100 сообщений в неделю\n- если вылетели по чистке, можно вернуться только 1 раз. то же правило для добровольного выхода\n\n3.2 неактивность: если вы не писали без причины и ретса более 3 дней — вы неактивны\n\nнаказание:\n- бан\n\n4. рест и выход из чата\n\n4.1 рест:\nуходить можно только с разрешения владельца (причина обязательна). запрещено уходить в рест за два дня до чистки.\n\n4.2 выход из флуда: хотите выйти? напишите причину (по желанию), свою роль и отметьте админа / владельца. если кто-то забыл отметить, убедительно просим сделать это того, кто заметил выход участника\n\n5. контент 18+\n\nв нашем чате категорически запрещено использование контента, который может быть воспринят как оскорбительный и нарушающий нормы приличия. сюда относится контент 18+, включая изображения, видео, гифки, стикеры и любой контент, в котором показывается или описывается насилие/нагота\n\nнаказание:\n- предупреждение (варн) на месяц \n- бан\n\n6. спам и команды\n\n6.1. текстовый спам: к текстовому спаму относятся сообщения, которые были отправлены пять раз подряд с одинаковым содержанием. это касается как текстовых сообщений, так и гифок, видео и стикеров. также спамом могут считаться повторяющиеся команды, используемые более десяти раз подряд. кроме того, спамом могут быть признаны чрезмерно длинные сообщения\n\n - 2+ созыва без причины = спам\n\n - админы могут созывать по важным вопросам, а участники только для игры в мафию\n\nнаказание:\n- мут на час \n\n7. личная информация и приглашения\n\n7.1 распространение личных данных: нельзя публиковать реальные имена, адреса, телефоны, ссылки на соцсети без согласия человека (ни в чате, ни в лс, если это делается со злым умыслом)\n\nнаказание:предупреждение (варн) навсегда\nили бан — по ситуации.\n\n8. роли и механики\n\n8.1 смена роли: пишите совладельцу или владельцу, указывая новую роль. можно взять только одну роль и сменить её один раз\n\n8.2 автоматическая защита от спамеров: в чат не смогут зайти аккаунты с пометкой от ириса «спамер», «юзер бот» и т.п.',8407034059,'2026-07-14 11:25:28');
/*!40000 ALTER TABLE `chat_rules` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `command_permissions`
--

DROP TABLE IF EXISTS `command_permissions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `command_permissions` (
  `command_key` varchar(64) NOT NULL,
  `min_level` tinyint NOT NULL,
  `updated_by` bigint DEFAULT NULL,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`command_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `command_permissions`
--

LOCK TABLES `command_permissions` WRITE;
/*!40000 ALTER TABLE `command_permissions` DISABLE KEYS */;
/*!40000 ALTER TABLE `command_permissions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `complaints`
--

DROP TABLE IF EXISTS `complaints`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `complaints` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `target_id` bigint NOT NULL,
  `reporter_id` bigint NOT NULL,
  `anonymous` tinyint(1) NOT NULL DEFAULT '0',
  `reason` text NOT NULL,
  `status` enum('pending','accepted','declined') NOT NULL DEFAULT 'pending',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `decided_by` bigint DEFAULT NULL,
  `decided_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_complaints_target` (`target_id`,`status`),
  KEY `idx_complaints_reporter` (`reporter_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `complaints`
--

LOCK TABLES `complaints` WRITE;
/*!40000 ALTER TABLE `complaints` DISABLE KEYS */;
INSERT INTO `complaints` VALUES (1,8114583471,5242991121,1,'попа.','declined','2026-07-12 15:52:59',8114583471,'2026-07-12 15:53:46'),(2,5242991121,8114583471,0,'Аска жыр!','pending','2026-07-14 20:30:16',NULL,NULL);
/*!40000 ALTER TABLE `complaints` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `custom_responses`
--

DROP TABLE IF EXISTS `custom_responses`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `custom_responses` (
  `user_id` bigint NOT NULL,
  `message` text NOT NULL,
  `added_by` bigint DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `custom_responses`
--

LOCK TABLES `custom_responses` WRITE;
/*!40000 ALTER TABLE `custom_responses` DISABLE KEYS */;
/*!40000 ALTER TABLE `custom_responses` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `known_users`
--

DROP TABLE IF EXISTS `known_users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `known_users` (
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `full_name` varchar(255) NOT NULL,
  `username` varchar(64) DEFAULT NULL,
  `last_seen_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `first_seen_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `invited_by` bigint DEFAULT NULL,
  PRIMARY KEY (`chat_id`,`user_id`),
  KEY `idx_known_users_seen` (`chat_id`,`last_seen_at` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `known_users`
--

LOCK TABLES `known_users` WRITE;
/*!40000 ALTER TABLE `known_users` DISABLE KEYS */;
INSERT INTO `known_users` VALUES (-1004315708356,7426341370,'Black Ameba','usuauusiaisi','2026-07-13 11:18:56','2026-07-13 11:18:56',8114583471),(-1004315708356,8114583471,'👨‍🦽','d30mant','2026-07-14 19:11:39','2026-07-13 11:18:29',NULL),(-1003811995090,5242991121,'минипека','minipeka_lelele','2026-07-15 18:44:21','2026-07-13 11:22:49',NULL),(-1003811995090,5707066924,'GEnaBEtoN','kilka76','2026-07-14 23:32:04','2026-07-13 11:18:29',NULL),(-1003811995090,7547410082,'Rei_herm','rei_herm','2026-07-15 18:38:06','2026-07-13 11:27:11',NULL),(-1003811995090,7790517846,'мурзик теплый','muerzek','2026-07-15 18:43:19','2026-07-13 11:18:29',NULL),(-1003811995090,8114583471,'👨‍🦽','d30mant','2026-07-15 18:39:02','2026-07-13 11:18:29',NULL),(-1003811995090,8407034059,'презеденет','meurme','2026-07-14 20:13:37','2026-07-13 11:18:29',NULL),(-1003811995090,8759004874,'меланин','e3quiorra','2026-07-14 20:18:29','2026-07-13 11:18:29',NULL),(-1003673552861,1307190691,'Biznes jr.','PLATOON54','2026-07-16 14:00:49','2026-07-16 13:26:53',NULL),(-1003673552861,1312624847,'шмонька','ekattusha','2026-07-15 20:42:59','2026-07-15 18:27:23',NULL),(-1003673552861,1475524466,'.','wmesh15','2026-07-16 14:51:17','2026-07-13 16:45:38',NULL),(-1003673552861,1508737016,'Сайонара Фараоновна','Sunlivery','2026-07-15 20:19:31','2026-07-14 03:12:38',NULL),(-1003673552861,1984456868,'Кирилл','kindlyercKB','2026-07-16 13:18:42','2026-07-13 11:18:29',NULL),(-1003673552861,5080664830,'𓆩𓆪Андрей𓆩𓆪 ㅤ̸̴̴̷̷͈̮͔̬̙̙̹͉͈̲̖͎͈͔̰͈͊̇̐̉̀̾͂̅͊͜͝͠ ̶̸̡̗̭̱̞̲͕̘͚̻̝̬̒̇̾͐͋̏̓̈́̍̕͘͘͘͜','Andrey_telegram10','2026-07-16 15:26:35','2026-07-13 11:18:29',NULL),(-1003673552861,5238563460,'𝙻𝙸𝙽𝙰','linalinovna','2026-07-16 15:04:57','2026-07-13 20:52:36',NULL),(-1003673552861,5242991121,'минипека','minipeka_lelele','2026-07-16 15:37:19','2026-07-13 11:18:29',NULL),(-1003673552861,5248704461,'TEROVER','TEROVER2','2026-07-12 15:21:47','2026-07-13 11:18:29',NULL),(-1003673552861,5400209637,'Джᥱᥔᥴ᧐н 𐋏ᥲᥴᴛ᧐ящ𝐢ᥔ','medic7910','2026-07-16 15:26:52','2026-07-16 15:24:08',NULL),(-1003673552861,5707066924,'GEnaBEtoN','kilka76','2026-07-16 15:09:42','2026-07-13 11:18:29',NULL),(-1003673552861,5771975148,'Лиса','BolemBolem','2026-07-15 18:10:28','2026-07-13 11:18:29',NULL),(-1003673552861,5918411165,'мс злой гном','mc_angry_dwarf','2026-07-16 15:38:23','2026-07-14 10:35:20',NULL),(-1003673552861,6105651374,'вишневая','waevviss','2026-07-13 20:01:10','2026-07-13 11:18:29',NULL),(-1003673552861,6542960747,'🍅','T_Tpiska','2026-07-15 19:46:56','2026-07-13 11:18:29',NULL),(-1003673552861,6723156345,'Реечка Аянамовна','ayanamireifanta','2026-07-13 22:36:57','2026-07-13 22:36:46',NULL),(-1003673552861,7329106105,'𝐹𝑖𝑘𝑢𝑠ᵕ̈','Turpentinee','2026-07-15 11:13:28','2026-07-15 11:07:48',NULL),(-1003673552861,7547410082,'Rei_herm','rei_herm','2026-07-16 15:14:05','2026-07-13 11:18:29',NULL),(-1003673552861,7579895039,'светаа🧁','svii1qwii','2026-07-14 08:41:24','2026-07-13 11:18:29',NULL),(-1003673552861,7790517846,'мурзик теплый','muerzek','2026-07-16 14:59:32','2026-07-15 15:02:04',NULL),(-1003673552861,7982777490,'Slient スリエント','Slient_S','2026-07-15 19:11:01','2026-07-13 11:18:29',NULL),(-1003673552861,8037189102,'зачем себя резать','WoFgiD03','2026-07-15 15:04:36','2026-07-13 11:18:29',NULL),(-1003673552861,8114583471,'👨‍🦽','d30mant','2026-07-16 15:14:04','2026-07-13 11:18:29',NULL),(-1003673552861,8149834084,'‍ ‍ ‍ ່ ‍ ‍‍ ‍ ‍ ‍ ‍ ‍ ‍‍ ‍ ‍ ‍ ‍ ‍ ‍ ່ ‍ ‍27🇫🇷','MaxVerstappenbol','2026-07-15 19:47:15','2026-07-13 11:18:29',NULL),(-1003673552861,8176377509,'︎ ︎ ︎ ᅠ ︎ ︎ ︎ ︎ ᅠ','Monver_76','2026-07-15 20:46:49','2026-07-15 19:28:20',NULL),(-1003673552861,8265845625,'Docty','geysku','2026-07-16 15:25:42','2026-07-16 13:58:49',NULL),(-1003673552861,8288451562,'Takumskiy #Dev1l [21]','dev1lllll','2026-07-16 14:55:05','2026-07-13 11:22:55',NULL),(-1003673552861,8407034059,'презеденет','meurme','2026-07-16 14:53:16','2026-07-13 11:18:29',NULL),(-1003673552861,8509346376,'ᅠᅠᅠᅠᅠᅠ','DOLKA_MANDARINKY','2026-07-16 15:37:05','2026-07-13 19:50:53',NULL),(-1003673552861,8650988494,'пятки мисато','pyatkimisato','2026-07-13 11:27:37','2026-07-13 11:27:34',NULL),(-1003673552861,8700500174,'White chease','Suber332','2026-07-16 15:37:06','2026-07-13 11:18:29',NULL),(-1003673552861,8759004874,'меланин','e3quiorra','2026-07-16 15:04:38','2026-07-13 11:18:29',NULL);
/*!40000 ALTER TABLE `known_users` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `logs`
--

DROP TABLE IF EXISTS `logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `logs` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `event_type` varchar(64) NOT NULL,
  `chat_id` bigint DEFAULT NULL,
  `actor_id` bigint DEFAULT NULL,
  `target_id` bigint DEFAULT NULL,
  `details` text,
  PRIMARY KEY (`id`),
  KEY `idx_logs_created` (`created_at`),
  KEY `idx_logs_type` (`event_type`)
) ENGINE=InnoDB AUTO_INCREMENT=318 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `logs`
--

LOCK TABLES `logs` WRITE;
/*!40000 ALTER TABLE `logs` DISABLE KEYS */;
INSERT INTO `logs` VALUES (1,'2026-07-12 14:26:07','special_response_set',NULL,8114583471,5242991121,NULL),(2,'2026-07-12 14:36:49','special_response_set',NULL,8114583471,5771975148,NULL),(3,'2026-07-12 14:39:17','special_response_removed',NULL,8114583471,5771975148,NULL),(4,'2026-07-12 14:45:14','admin_added',NULL,8114583471,5707066924,'⭐ Администратор'),(5,'2026-07-12 14:59:47','rp_ударить',-1003673552861,7790517846,5707066924,NULL),(6,'2026-07-12 14:59:47','rp_ударить',-1003673552861,5242991121,8114583471,NULL),(7,'2026-07-12 15:01:03','testmode_on',NULL,8114583471,NULL,NULL),(8,'2026-07-12 15:02:04','special_response_removed',NULL,8114583471,5242991121,NULL),(9,'2026-07-12 15:02:23','testmode_off',NULL,8114583471,NULL,NULL),(10,'2026-07-12 15:02:25','testmode_on',NULL,8114583471,NULL,NULL),(11,'2026-07-12 15:03:16','rp_ударить',-1003673552861,7790517846,5707066924,NULL),(12,'2026-07-12 15:03:52','request_created',NULL,5242991121,NULL,'ч тебе череп проломлю ебанина тупая'),(13,'2026-07-12 15:04:02','request_rejected',NULL,8114583471,5242991121,NULL),(14,'2026-07-12 15:04:02','request_rejected',NULL,7790517846,5242991121,NULL),(15,'2026-07-12 15:04:22','reward',-1003673552861,7790517846,8114583471,'degree=7 id=1'),(16,'2026-07-12 15:11:01','rp_погладить',-1003673552861,8114583471,5242991121,NULL),(17,'2026-07-12 15:21:15','request_created',NULL,8114583471,NULL,'🔄 Обновить'),(18,'2026-07-12 15:21:29','request_accepted',NULL,7790517846,8114583471,NULL),(19,'2026-07-12 15:21:29','testmode_off',NULL,8114583471,NULL,NULL),(20,'2026-07-12 15:35:00','admin_added',NULL,8114583471,5242991121,'🛡 Модератор'),(21,'2026-07-12 15:52:59','complaint_filed',NULL,5242991121,8114583471,'попа.'),(22,'2026-07-12 15:53:46','complaint_declined',NULL,8114583471,8114583471,'жалоба №1'),(23,'2026-07-12 16:03:34','request_created',NULL,8759004874,NULL,'потомучто я бетмен'),(24,'2026-07-12 16:03:56','request_rejected',NULL,8114583471,8759004874,NULL),(25,'2026-07-12 17:51:52','rp_ударить',-1003673552861,7790517846,8759004874,NULL),(26,'2026-07-12 17:56:38','rp_ударить',-1003673552861,8114583471,7790517846,NULL),(27,'2026-07-12 18:04:27','marriage_created',-1003673552861,8759004874,7790517846,NULL),(28,'2026-07-12 18:05:23','nickname_set',-1003673552861,7790517846,NULL,'мурзик ористократ'),(29,'2026-07-12 18:06:56','nickname_set',-1003673552861,5242991121,NULL,'.'),(30,'2026-07-12 18:09:30','marriage_created',-1003673552861,5242991121,8114583471,NULL),(31,'2026-07-13 06:39:58','mute',-1003673552861,7790517846,5080664830,NULL),(32,'2026-07-13 06:40:47','mute',-1003673552861,7790517846,5080664830,'6.1. спам гифками около 10 раз'),(33,'2026-07-13 06:41:27','unmute',-1003673552861,7790517846,5080664830,NULL),(34,'2026-07-13 06:41:34','mute',-1003673552861,7790517846,5080664830,'час 6.1. спам гифками около 10 раз'),(35,'2026-07-13 08:11:43','admin_added',-1003673552861,7790517846,8759004874,'🛡 Модератор'),(36,'2026-07-13 08:13:36','admin_added',-1003673552861,7790517846,5707066924,'👑 Старший администратор'),(37,'2026-07-13 08:14:06','admin_added',-1003673552861,7790517846,7547410082,'⭐ Администратор'),(38,'2026-07-13 08:14:22','admin_added',-1003673552861,7790517846,5242991121,'⭐ Администратор'),(39,'2026-07-13 08:15:24','reward',-1003673552861,7790517846,8759004874,'degree=5 id=2'),(40,'2026-07-13 08:16:53','reward',-1003673552861,8114583471,7790517846,'degree=8 id=3'),(41,'2026-07-13 08:27:07','mute',-1003673552861,8114583471,6105651374,NULL),(42,'2026-07-13 08:27:30','unmute',-1003673552861,8114583471,6105651374,NULL),(43,'2026-07-13 08:27:44','unmute',-1003673552861,7790517846,5080664830,NULL),(44,'2026-07-13 08:27:56','unmute',-1003673552861,8114583471,5080664830,NULL),(45,'2026-07-13 08:52:27','timer_created',-1004315708356,8114583471,NULL,'Проверка'),(46,'2026-07-13 08:53:02','timer_created',-1003673552861,8114583471,NULL,'проверка'),(47,'2026-07-13 08:53:16','delete_messages_bulk',-1003673552861,8114583471,NULL,'7'),(48,'2026-07-13 08:54:03','timer_fired',-1003673552861,NULL,NULL,'проверка'),(49,'2026-07-13 11:18:32','timer_fired',-1004315708356,NULL,NULL,'Проверка'),(50,'2026-07-13 11:18:45','call_start',-1004315708356,8114583471,NULL,NULL),(51,'2026-07-13 11:19:02','call_start',-1004315708356,8114583471,NULL,NULL),(52,'2026-07-13 11:19:33','warn',-1003673552861,5242991121,8759004874,NULL),(53,'2026-07-13 11:19:40','warn',-1003673552861,7790517846,5707066924,NULL),(54,'2026-07-13 11:20:04','call_start',-1004315708356,8114583471,NULL,NULL),(55,'2026-07-13 11:22:06','call_start',-1003811995090,8114583471,NULL,NULL),(56,'2026-07-13 11:22:46','call_start',-1003811995090,7790517846,NULL,'мурзик ориджинал'),(57,'2026-07-13 11:27:12','call_start',-1003811995090,8114583471,NULL,NULL),(58,'2026-07-13 11:27:40','unreg',-1003811995090,8759004874,NULL,NULL),(59,'2026-07-13 11:40:24','call_start',-1003673552861,7790517846,NULL,'оео'),(60,'2026-07-13 11:46:44','chat_unlock',-1003673552861,5242991121,NULL,NULL),(61,'2026-07-13 11:56:49','mute',-1003673552861,7790517846,8759004874,'3 часа'),(62,'2026-07-13 11:57:25','mute',-1003673552861,7790517846,5707066924,'3 часа'),(63,'2026-07-13 12:15:22','tg_admin_granted',-1003811995090,8114583471,8114583471,NULL),(64,'2026-07-13 12:23:32','rp_укусить',-1004315708356,8114583471,8912566968,NULL),(65,'2026-07-13 12:27:33','rp_погладить',-1004315708356,8114583471,8912566968,NULL),(66,'2026-07-13 12:27:41','rp_погладить',-1004315708356,8114583471,8912566968,NULL),(67,'2026-07-13 12:27:43','rp_погладить',-1004315708356,8114583471,8912566968,NULL),(68,'2026-07-13 12:44:42','rp_покормить',-1004315708356,8114583471,8912566968,NULL),(69,'2026-07-13 12:45:14','rp_покормить',-1004315708356,8114583471,8912566968,NULL),(70,'2026-07-13 12:48:23','nickname_set',-1004315708356,8114583471,NULL,'хуйлан'),(71,'2026-07-13 12:48:29','rp_покормить',-1004315708356,8114583471,8912566968,NULL),(72,'2026-07-13 12:55:25','rp_покормить',-1003673552861,8114583471,5242991121,NULL),(73,'2026-07-13 15:26:40','unmute',-1003673552861,7790517846,8759004874,NULL),(74,'2026-07-13 15:27:00','unmute',-1003673552861,7790517846,5707066924,NULL),(75,'2026-07-13 15:41:50','call_start',-1003673552861,7790517846,NULL,'бинго эй, сделаетйе\nкто сделает - награду на 4'),(76,'2026-07-13 16:45:40','call_start',-1003673552861,7547410082,NULL,'нью Тодзи'),(77,'2026-07-13 19:50:55','call_start',-1003673552861,7547410082,NULL,'нью ева 01'),(78,'2026-07-13 19:54:18','marriage_created',-1003673552861,8509346376,8037189102,NULL),(79,'2026-07-13 19:55:09','rp_поцеловать',-1003673552861,8509346376,8037189102,NULL),(80,'2026-07-13 19:55:20','call_start',-1003673552861,5242991121,NULL,'мафия'),(81,'2026-07-13 20:52:39','call_start',-1003673552861,7547410082,NULL,'нью ева 05'),(82,'2026-07-13 21:00:49','rp_поцеловать',-1003673552861,8509346376,5238563460,NULL),(83,'2026-07-13 21:01:28','rp_поцеловать',-1003673552861,5238563460,8509346376,NULL),(84,'2026-07-13 21:08:36','nickname_set',-1003673552861,8509346376,NULL,'Маринка Макинами'),(85,'2026-07-13 21:08:53','nickname_set',-1003673552861,5238563460,NULL,'Линочка'),(86,'2026-07-13 21:10:05','rp_поцеловать',-1003673552861,8509346376,5238563460,NULL),(87,'2026-07-13 21:10:05','rp_поцеловать',-1003673552861,5238563460,8509346376,NULL),(88,'2026-07-13 21:22:05','delete_messages_bulk',-1003811995090,8114583471,NULL,'3'),(89,'2026-07-13 21:22:11','delete_messages_bulk',-1003811995090,8114583471,NULL,'3'),(90,'2026-07-13 21:22:58','rest_requested',-1003673552861,8114583471,NULL,'2 дня | я хуйло'),(91,'2026-07-13 21:23:09','rest_rejected',-1003673552861,8114583471,8114583471,NULL),(92,'2026-07-13 21:42:09','rest_requested',-1003673552861,8114583471,NULL,'1 день | устал'),(93,'2026-07-13 21:42:34','rest_rejected',-1003673552861,8114583471,8114583471,NULL),(94,'2026-07-13 22:01:39','norm_set',-1004315708356,8114583471,NULL,'100'),(95,'2026-07-13 22:01:58','norm_unset',-1004315708356,8114583471,NULL,NULL),(96,'2026-07-13 22:02:15','norm_set',-1003673552861,8114583471,NULL,'100'),(97,'2026-07-14 03:12:40','call_start',-1003673552861,7547410082,NULL,'нью Исрафель'),(98,'2026-07-14 03:18:19','nickname_set',-1003673552861,1508737016,NULL,'Йсраэль Йегуда'),(99,'2026-07-14 06:25:50','rp_поцеловать',-1003673552861,5238563460,8509346376,NULL),(100,'2026-07-14 06:32:22','rp_поцеловать',-1003673552861,8509346376,5238563460,NULL),(101,'2026-07-14 07:30:42','relationship_created',-1003673552861,8114583471,5242991121,NULL),(102,'2026-07-14 07:31:23','nickname_set',-1003673552861,5242991121,NULL,'алкоголизм'),(103,'2026-07-14 07:31:44','relationship_broken',-1003673552861,8114583471,5242991121,NULL),(104,'2026-07-14 07:31:53','nickname_set',-1003673552861,8114583471,NULL,'хуйло'),(105,'2026-07-14 07:57:49','call_start',-1003673552861,7790517846,NULL,'эй а бинго риьбятд'),(106,'2026-07-14 08:12:57','tg_admin_revoked',-1003811995090,8114583471,8114583471,NULL),(107,'2026-07-14 08:13:02','tg_admin_granted',-1003811995090,8114583471,8114583471,NULL),(108,'2026-07-14 08:15:08','admin_added',-1003811995090,8114583471,5707066924,'🛡 Модератор'),(109,'2026-07-14 08:16:51','admin_added',-1003811995090,8114583471,5707066924,'👑 Старший администратор'),(110,'2026-07-14 08:17:54','admin_mute',-1003811995090,5707066924,8114583471,NULL),(111,'2026-07-14 08:27:06','rp_поцеловать',-1003673552861,5238563460,8509346376,NULL),(112,'2026-07-14 08:29:29','rest_requested',-1003673552861,8114583471,NULL,'3 часа | дайте отдых паже'),(113,'2026-07-14 08:30:52','rest_approved',-1003673552861,8114583471,8114583471,NULL),(114,'2026-07-14 08:34:56','admin_rights_restored',-1003811995090,NULL,8114583471,NULL),(115,'2026-07-14 08:37:12','tg_admin_granted',-1003673552861,8114583471,5242991121,NULL),(116,'2026-07-14 08:37:20','tg_admin_granted',-1003673552861,7790517846,5707066924,NULL),(117,'2026-07-14 08:37:35','call_start',-1003673552861,5707066924,NULL,'Нью гендо'),(118,'2026-07-14 08:39:18','tg_admin_granted',-1003673552861,8114583471,8114583471,NULL),(119,'2026-07-14 08:39:24','tg_admin_right_toggled',-1003673552861,8114583471,8114583471,'can_change_info=True'),(120,'2026-07-14 08:39:25','tg_admin_right_toggled',-1003673552861,8114583471,8114583471,'can_promote_members=True'),(121,'2026-07-14 09:10:48','unreg',-1003673552861,5242991121,NULL,NULL),(122,'2026-07-14 09:11:05','unreg',-1003673552861,5080664830,NULL,NULL),(123,'2026-07-14 10:28:52','tg_admin_granted',-1003811995090,7790517846,8114583471,NULL),(124,'2026-07-14 10:29:15','admin_mute',-1003811995090,7790517846,8114583471,NULL),(125,'2026-07-14 10:32:13','tg_admin_granted',-1003673552861,7790517846,7547410082,NULL),(126,'2026-07-14 10:32:37','tg_admin_granted',-1003673552861,7790517846,7547410082,NULL),(127,'2026-07-14 10:32:43','tg_admin_right_toggled',-1003673552861,7790517846,7547410082,'can_change_info=True'),(128,'2026-07-14 10:33:27','tg_admin_granted',-1003673552861,7790517846,8759004874,NULL),(129,'2026-07-14 10:37:07','tg_admin_revoked',-1003673552861,7790517846,7547410082,NULL),(130,'2026-07-14 10:37:14','admin_rights_restored',-1003811995090,NULL,8114583471,NULL),(131,'2026-07-14 10:37:16','tg_admin_granted',-1003673552861,7790517846,7547410082,NULL),(132,'2026-07-14 10:37:19','tg_admin_right_toggled',-1003673552861,7790517846,7547410082,'can_change_info=True'),(133,'2026-07-14 10:37:59','tg_admin_granted',-1003673552861,7790517846,5707066924,NULL),(134,'2026-07-14 10:38:02','tg_admin_right_toggled',-1003673552861,7790517846,5707066924,'can_change_info=True'),(135,'2026-07-14 10:43:50','call_start',-1003811995090,8114583471,NULL,'ребята у кого есть список ролей'),(136,'2026-07-14 10:56:45','tg_admin_revoked',-1003673552861,8114583471,7547410082,NULL),(137,'2026-07-14 10:56:52','tg_admin_granted',-1003673552861,8114583471,7547410082,NULL),(138,'2026-07-14 10:56:55','tg_admin_right_toggled',-1003673552861,8114583471,7547410082,'can_promote_members=True'),(139,'2026-07-14 11:21:58','admin_added',-1003673552861,8114583471,8407034059,'👑 Старший администратор'),(140,'2026-07-14 11:23:55','set_rules',-1003673552861,8407034059,NULL,NULL),(141,'2026-07-14 11:25:29','set_rules',-1003673552861,8407034059,NULL,NULL),(142,'2026-07-14 11:29:37','role_propose',-1004315708356,8114583471,NULL,'Хуйло'),(143,'2026-07-14 11:39:35','role_import',-1003811995090,8114583471,NULL,'65'),(144,'2026-07-14 11:41:33','role_import',-1003673552861,8114583471,NULL,'65'),(145,'2026-07-14 11:41:46','delete_message',-1003673552861,8114583471,8912566968,NULL),(146,'2026-07-14 11:43:15','role_force_give',-1003673552861,8114583471,8114583471,'Копье Лонгина'),(147,'2026-07-14 11:44:00','delete_messages_bulk',-1003673552861,8114583471,NULL,'10'),(148,'2026-07-14 11:44:05','delete_messages_bulk',-1003673552861,8114583471,NULL,'5'),(149,'2026-07-14 11:56:06','role_force_give',-1003673552861,8114583471,8114583471,'Копье Лонгина'),(150,'2026-07-14 12:10:23','role_import',-1003811995090,8114583471,NULL,'0'),(151,'2026-07-14 12:10:48','role_import',-1003811995090,8114583471,NULL,'0'),(152,'2026-07-14 12:11:29','role_import',-1004315708356,8114583471,NULL,'65'),(153,'2026-07-14 12:11:55','role_force_give',-1004315708356,8114583471,8114583471,'Копье Лонгина'),(154,'2026-07-14 12:12:37','tg_admin_granted',-1003673552861,8114583471,8114583471,NULL),(155,'2026-07-14 12:12:43','tg_admin_right_toggled',-1003673552861,8114583471,8114583471,'can_change_info=True'),(156,'2026-07-14 12:12:43','tg_admin_right_toggled',-1003673552861,8114583471,8114583471,'can_promote_members=True'),(157,'2026-07-14 12:17:11','role_force_give',-1003673552861,8114583471,5707066924,'Ева-02'),(158,'2026-07-14 13:04:31','role_force_give',-1003673552861,5707066924,7790517846,'Каору Нагиса'),(159,'2026-07-14 13:05:32','role_propose',-1003673552861,8114583471,NULL,'Аска'),(160,'2026-07-14 13:14:46','role_force_give',-1003673552861,8114583471,5242991121,'Сорью Аска'),(161,'2026-07-14 13:19:10','role_force_give',-1003673552861,7790517846,5400209637,'Сперма Синдзи'),(162,'2026-07-14 13:19:41','role_force_give',-1003673552861,7790517846,6542960747,'Ева-03'),(163,'2026-07-14 13:19:58','role_force_give',-1003673552861,8114583471,7547410082,'Рей Аянами'),(164,'2026-07-14 13:20:39','role_force_give',-1003673552861,7790517846,1508737016,'Исрафель'),(165,'2026-07-14 13:22:33','role_force_give',-1003673552861,7790517846,8759004874,'Синдзи Икари'),(166,'2026-07-14 13:22:37','chat_lock',-1003673552861,7790517846,NULL,NULL),(167,'2026-07-14 13:22:53','tg_admin_granted',-1003673552861,8407034059,7790517846,NULL),(168,'2026-07-14 13:23:16','tg_admin_right_toggled',-1003673552861,8114583471,7790517846,'can_change_info=True'),(169,'2026-07-14 13:23:17','tg_admin_right_toggled',-1003673552861,8114583471,7790517846,'can_promote_members=True'),(170,'2026-07-14 13:24:52','role_force_give',-1003673552861,7790517846,8037189102,'Редзи Кадзи'),(171,'2026-07-14 13:25:08','role_force_give',-1003673552861,8114583471,5771975148,'Юи Икари'),(172,'2026-07-14 13:25:21','role_force_give',-1003673552861,7790517846,1984456868,'Мина-тян'),(173,'2026-07-14 13:25:50','role_force_give',-1003673552861,7790517846,6723156345,'Лилит'),(174,'2026-07-14 13:26:07','role_force_give',-1003673552861,7790517846,8509346376,'Мари Макинами'),(175,'2026-07-14 13:26:56','tg_admin_granted',-1003673552861,7790517846,5707066924,NULL),(176,'2026-07-14 13:27:00','tg_admin_right_toggled',-1003673552861,8114583471,5707066924,'can_change_info=True'),(177,'2026-07-14 13:27:01','tg_admin_right_toggled',-1003673552861,8114583471,5707066924,'can_promote_members=True'),(178,'2026-07-14 13:27:07','role_force_give',-1003673552861,5242991121,7329106105,'Пиво Мисато'),(179,'2026-07-14 13:28:26','tg_admin_granted',-1003673552861,7790517846,5707066924,NULL),(180,'2026-07-14 13:28:31','tg_admin_right_toggled',-1003673552861,8114583471,5707066924,'can_change_info=True'),(181,'2026-07-14 13:28:31','tg_admin_right_toggled',-1003673552861,8114583471,5707066924,'can_promote_members=True'),(182,'2026-07-14 13:28:33','tg_admin_right_toggled',-1003673552861,7790517846,5707066924,'can_change_info=False'),(183,'2026-07-14 13:28:33','tg_admin_right_toggled',-1003673552861,8114583471,5707066924,'can_promote_members=False'),(184,'2026-07-14 13:28:37','tg_admin_right_toggled',-1003673552861,8114583471,5707066924,'can_promote_members=True'),(185,'2026-07-14 13:28:38','tg_admin_right_toggled',-1003673552861,8114583471,5707066924,'can_promote_members=False'),(186,'2026-07-14 13:28:43','tg_admin_right_toggled',-1003673552861,8114583471,5707066924,'can_promote_members=True'),(187,'2026-07-14 13:28:51','role_force_give',-1003673552861,5707066924,6881601407,'Гендо Икари'),(188,'2026-07-14 13:29:46','role_force_give',-1003673552861,5242991121,1475524466,'Тодзи Судзухара'),(189,'2026-07-14 13:31:40','role_force_give',-1003673552861,5707066924,8037189102,'Редзи Кадзи'),(190,'2026-07-14 13:31:42','role_force_give',-1003673552861,7790517846,8288451562,'Арбуз'),(191,'2026-07-14 13:32:43','role_force_give',-1003673552861,7790517846,5080664830,'Пен Пен'),(192,'2026-07-14 13:32:59','role_force_give',-1003673552861,5707066924,5400209637,'Сперма Синдзи'),(193,'2026-07-14 13:33:44','role_force_give',-1003673552861,5707066924,8700500174,'Мисато Кацураги'),(194,'2026-07-14 13:33:51','role_force_give',-1003673552861,7790517846,8149834084,'Макото Хюга'),(195,'2026-07-14 13:34:30','role_force_give',-1003673552861,7790517846,6881601407,'Гендо Икари'),(196,'2026-07-14 13:35:32','role_force_give',-1003673552861,5707066924,1508737016,'Исрафель'),(197,'2026-07-14 13:35:44','role_force_give',-1003673552861,7790517846,5238563460,'Ева-05'),(198,'2026-07-14 13:35:55','role_force_give',-1003673552861,5707066924,5238563460,'Ева-05'),(199,'2026-07-14 13:37:58','role_force_give',-1003673552861,5707066924,7982777490,'Аска Сикинами'),(200,'2026-07-14 13:38:02','chat_unlock',-1003673552861,7790517846,NULL,NULL),(201,'2026-07-14 13:41:03','role_force_give',-1003673552861,5707066924,6516227864,'Копье Кассиуса'),(202,'2026-07-14 13:42:32','rp_поцеловать',-1003673552861,7790517846,5707066924,NULL),(203,'2026-07-14 13:42:40','role_force_give',-1003673552861,5707066924,8509346376,'Ева-01'),(204,'2026-07-14 13:45:59','role_force_give',-1003673552861,5707066924,7579895039,'Доктор Кацураги'),(205,'2026-07-14 13:47:43','role_force_give',-1003673552861,5707066924,6105651374,'Наоко Акаги'),(206,'2026-07-14 13:48:22','role_force_give',-1003673552861,5707066924,8670492812,'Рицуко Акаги'),(207,'2026-07-14 13:49:38','role_take',-1003811995090,8114583471,NULL,'Ева-06'),(208,'2026-07-14 14:01:07','role_release',-1003811995090,8114583471,NULL,'Ева-06'),(209,'2026-07-14 14:26:45','role_force_give',-1003811995090,8114583471,5707066924,'Ева-02'),(210,'2026-07-14 14:27:04','role_force_give',-1003811995090,8114583471,7790517846,'Каору Нагиса'),(211,'2026-07-14 14:27:22','role_force_give',-1003811995090,8114583471,5242991121,'Сорью Аска'),(212,'2026-07-14 14:29:42','role_force_give',-1003811995090,8114583471,7547410082,'Рей Аянами'),(213,'2026-07-14 14:34:22','role_force_give',-1003811995090,8114583471,6542960747,'Ева-03'),(214,'2026-07-14 14:34:40','role_force_give',-1003811995090,8114583471,1508737016,'Исрафель'),(215,'2026-07-14 14:35:30','role_force_give',-1003811995090,8114583471,8759004874,'Синдзи Икари'),(216,'2026-07-14 14:35:46','role_force_give',-1003811995090,8114583471,8037189102,'Редзи Кадзи'),(217,'2026-07-14 14:36:04','role_force_give',-1003811995090,8114583471,8037189102,'Редзи Кадзи'),(218,'2026-07-14 14:36:15','role_force_give',-1003811995090,8114583471,5771975148,'Юи Икари'),(219,'2026-07-14 14:36:23','role_force_give',-1003811995090,8114583471,1984456868,'Мина-тян'),(220,'2026-07-14 14:36:28','role_force_give',-1003811995090,8114583471,8037189102,'Редзи Кадзи'),(221,'2026-07-14 14:37:00','role_force_give',-1003811995090,8114583471,5771975148,'Юи Икари'),(222,'2026-07-14 14:37:23','role_force_give',-1003811995090,8114583471,6723156345,'Лилит'),(223,'2026-07-14 14:37:44','role_force_give',-1003811995090,8114583471,8509346376,'Мари Макинами'),(224,'2026-07-14 14:38:15','role_force_give',-1003811995090,8114583471,6881601407,'Гендо Икари'),(225,'2026-07-14 14:38:36','role_force_give',-1003811995090,8114583471,1475524466,'Тодзи Судзухара'),(226,'2026-07-14 14:39:17','role_force_give',-1003811995090,8114583471,8288451562,'Арбуз'),(227,'2026-07-14 14:39:23','role_force_give',-1003811995090,8114583471,8037189102,'Редзи Кадзи'),(228,'2026-07-14 14:39:40','role_force_give',-1003811995090,8114583471,5080664830,'Пен Пен'),(229,'2026-07-14 14:40:24','role_force_give',-1003811995090,8114583471,8700500174,'Мисато Кацураги'),(230,'2026-07-14 14:40:54','role_force_give',-1003811995090,8114583471,8149834084,'Макото Хюга'),(231,'2026-07-14 14:41:20','role_force_give',-1003811995090,8114583471,6881601407,'Гендо Икари'),(232,'2026-07-14 14:41:43','role_force_give',-1003811995090,8114583471,1508737016,'Исрафель'),(233,'2026-07-14 14:42:22','role_force_give',-1003811995090,8114583471,7579895039,'Доктор Кацураги'),(234,'2026-07-14 14:43:05','role_force_give',-1003811995090,8114583471,6105651374,'Наоко Акаги'),(235,'2026-07-14 14:43:56','role_force_give',-1003811995090,8114583471,8509346376,'Ева-01'),(236,'2026-07-14 14:44:17','role_force_give',-1003811995090,8114583471,5238563460,'Ева-05'),(237,'2026-07-14 14:45:31','role_force_give',-1003811995090,8114583471,7982777490,'Аска Сикинами'),(238,'2026-07-14 14:45:58','role_force_give',-1003811995090,8114583471,5400209637,'Сперма Синдзи'),(239,'2026-07-14 14:46:19','role_force_give',-1003811995090,8114583471,7329106105,'Пиво Мисато'),(240,'2026-07-14 14:46:38','role_force_give',-1003811995090,8114583471,8670492812,'Рицуко Акаги'),(241,'2026-07-14 14:46:55','role_force_give',-1003811995090,8114583471,6516227864,'Копье Кассиуса'),(242,'2026-07-14 14:47:45','role_force_give',-1003811995090,8114583471,8114583471,'Копье Лонгина'),(243,'2026-07-14 15:11:18','role_force_give',-1003811995090,8114583471,8114583471,'Ева-04'),(244,'2026-07-14 15:11:42','role_force_take',-1003811995090,8114583471,8114583471,'Ева-04'),(245,'2026-07-14 15:12:17','role_force_give',-1003811995090,8114583471,8114583471,'Фанта Рей'),(246,'2026-07-14 15:12:21','role_force_take',-1003811995090,8114583471,8114583471,'Фанта Рей'),(247,'2026-07-14 15:12:37','role_force_give',-1003811995090,8114583471,8114583471,'Кодзо Фуюцуки'),(248,'2026-07-14 15:13:00','role_force_give',-1003811995090,8114583471,8114583471,'Лелиэль'),(249,'2026-07-14 15:13:43','role_take',-1003811995090,8114583471,NULL,'Копье Лонгина'),(250,'2026-07-14 16:06:35','tg_admin_revoked',-1003673552861,8114583471,7547410082,NULL),(251,'2026-07-14 16:06:40','tg_admin_granted',-1003673552861,8114583471,7547410082,NULL),(252,'2026-07-14 16:06:42','tg_admin_right_toggled',-1003673552861,8114583471,7547410082,'can_manage_direct_messages=True'),(253,'2026-07-14 16:06:46','tg_admin_right_toggled',-1003673552861,8114583471,7547410082,'can_promote_members=True'),(254,'2026-07-14 16:06:47','tg_admin_right_toggled',-1003673552861,8114583471,7547410082,'can_change_info=True'),(255,'2026-07-14 16:07:27','tg_admin_revoked',-1003673552861,8114583471,8114583471,NULL),(256,'2026-07-14 16:07:32','tg_admin_granted',-1003673552861,8114583471,8114583471,NULL),(257,'2026-07-14 16:07:33','tg_admin_right_toggled',-1003673552861,8114583471,8114583471,'can_manage_direct_messages=True'),(258,'2026-07-14 16:07:34','tg_admin_right_toggled',-1003673552861,8114583471,8114583471,'can_promote_members=True'),(259,'2026-07-14 16:07:34','tg_admin_right_toggled',-1003673552861,8114583471,8114583471,'can_change_info=True'),(260,'2026-07-14 16:10:54','tg_admin_revoked',-1003673552861,8114583471,8114583471,NULL),(261,'2026-07-14 16:10:58','tg_admin_granted',-1003673552861,8114583471,8114583471,NULL),(262,'2026-07-14 16:11:16','tg_admin_granted',-1003673552861,8114583471,7547410082,NULL),(263,'2026-07-14 16:11:19','tg_admin_right_toggled',-1003673552861,8114583471,7547410082,'can_manage_tags=False'),(264,'2026-07-14 16:11:20','tg_admin_right_toggled',-1003673552861,8114583471,7547410082,'can_manage_tags=True'),(265,'2026-07-14 16:11:37','tg_admin_granted',-1003673552861,8114583471,5242991121,NULL),(266,'2026-07-14 16:11:59','rp_обнять',-1003673552861,5242991121,8114583471,NULL),(267,'2026-07-14 16:12:30','rp_поцеловать',-1003673552861,8114583471,5242991121,NULL),(268,'2026-07-14 16:21:25','reward',-1003673552861,7547410082,8114583471,'degree=2 id=4'),(269,'2026-07-14 16:22:13','rp_отсосать',-1003673552861,8114583471,6881601407,NULL),(270,'2026-07-14 16:22:54','rp_трахнуть',-1003673552861,1984456868,6881601407,NULL),(271,'2026-07-14 16:25:25','rp_выебать',-1003673552861,8114583471,6881601407,NULL),(272,'2026-07-14 16:27:12','rest_requested',-1003673552861,8114583471,NULL,'7 дней | идитенахуй я чилить'),(273,'2026-07-14 16:27:37','rp_спеть серенаду',-1003673552861,8114583471,5242991121,NULL),(274,'2026-07-14 16:32:22','rp_выебать',-1003673552861,6881601407,8114583471,NULL),(275,'2026-07-14 16:38:42','rp_чмок',-1004315708356,8114583471,707693258,NULL),(276,'2026-07-14 16:38:50','rp_чмок',-1003673552861,8114583471,6881601407,NULL),(277,'2026-07-14 16:54:37','rp_выебать',-1003673552861,6881601407,8114583471,NULL),(278,'2026-07-14 16:55:20','rp_выебать',-1003673552861,6881601407,1475524466,NULL),(279,'2026-07-14 17:02:59','rest_approved',-1003673552861,5707066924,8114583471,NULL),(280,'2026-07-14 17:05:19','rp_чмок',-1003673552861,6881601407,8700500174,NULL),(281,'2026-07-14 17:21:47','rp_погладить',-1003673552861,7790517846,8037189102,NULL),(282,'2026-07-14 17:33:54','rp_выебать',-1003673552861,6881601407,5242991121,NULL),(283,'2026-07-14 17:47:25','rp_выебать',-1003673552861,6881601407,8288451562,NULL),(284,'2026-07-14 17:56:53','nickname_set',-1003673552861,1508737016,NULL,'Йесраель Йигурда'),(285,'2026-07-14 18:18:09','reward',-1003673552861,8114583471,5771975148,'degree=3 id=5'),(286,'2026-07-14 19:22:32','rp_поцеловать',-1003673552861,5238563460,8509346376,NULL),(287,'2026-07-14 19:25:31','rp_трахнуть',-1003673552861,8509346376,5238563460,NULL),(288,'2026-07-14 19:27:22','rp_трахнуть',-1003673552861,5238563460,8509346376,NULL),(289,'2026-07-14 19:35:20','role_delete_on_leave',-1003673552861,6881601407,NULL,'Гендо Икари'),(290,'2026-07-14 20:13:38','call_start',-1003811995090,7790517846,NULL,'у каво кстт дочьуа к тт уберити мой юз @meurme и если места будет бота добавьте заодно'),(291,'2026-07-14 20:15:25','warn',-1003673552861,8114583471,1984456868,'ахуел ты'),(292,'2026-07-14 20:15:31','unwarn',-1003673552861,8114583471,1984456868,NULL),(293,'2026-07-14 20:17:58','role_delete_on_leave',-1003673552861,7790517846,NULL,'Каору Нагиса'),(294,'2026-07-14 20:30:16','complaint_filed',NULL,8114583471,5242991121,'Аска жыр!'),(295,'2026-07-14 23:19:38','rest_requested',-1003673552861,5707066924,NULL,'3 часа | я голодоранец'),(296,'2026-07-14 23:19:43','rest_rejected',-1003673552861,5707066924,5707066924,NULL),(297,'2026-07-14 23:31:08','rest_requested',-1003673552861,8037189102,NULL,'14 дней | мненадо очень'),(298,'2026-07-14 23:31:23','rest_approved',-1003673552861,5707066924,8037189102,NULL),(299,'2026-07-15 14:40:06','delete_message',-1003673552861,8114583471,5160386506,NULL),(300,'2026-07-15 17:38:42','tg_admin_granted',-1003673552861,8114583471,7790517846,NULL),(301,'2026-07-15 17:38:44','tg_admin_right_toggled',-1003673552861,8114583471,7790517846,'can_change_info=True'),(302,'2026-07-15 17:38:44','tg_admin_right_toggled',-1003673552861,8114583471,7790517846,'can_promote_members=True'),(303,'2026-07-15 18:31:16','call_start',-1003673552861,5707066924,NULL,'рей q'),(304,'2026-07-15 18:34:09','role_propose',-1003811995090,8114583471,NULL,'Рей-q'),(305,'2026-07-15 18:34:13','role_approve',-1003811995090,8114583471,NULL,'Рей-q'),(306,'2026-07-15 18:34:33','role_force_give',-1003811995090,8114583471,1312624847,'Рей-q'),(307,'2026-07-15 18:38:50','rest_requested',-1003673552861,5242991121,NULL,'30 дней | лагер.'),(308,'2026-07-15 18:40:13','rest_approved',-1003673552861,7790517846,5242991121,NULL),(309,'2026-07-15 18:43:12','admin_added',-1003673552861,8114583471,5707066924,'🛡 Модератор'),(310,'2026-07-15 18:43:40','admin_added',-1003673552861,8114583471,5707066924,'👑 Старший администратор'),(311,'2026-07-15 18:49:27','role_force_give',-1003811995090,8114583471,5918411165,'Ева-06'),(312,'2026-07-15 19:28:30','call_start',-1003673552861,7547410082,NULL,'нью кенсуке аида'),(313,'2026-07-15 19:29:31','role_force_give',-1003811995090,5242991121,8176377509,'Кэнсукэ Аида'),(314,'2026-07-15 19:55:09','reward',-1003673552861,8114583471,8176377509,'degree=1 id=6'),(315,'2026-07-15 20:27:13','marriage_declined',-1003673552861,8176377509,1312624847,NULL),(316,'2026-07-15 20:43:57','rp_спеть серенаду',-1003673552861,8114583471,5242991121,NULL),(317,'2026-07-16 14:53:16','call_start',-1003673552861,7790517846,NULL,NULL);
/*!40000 ALTER TABLE `logs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `marriages`
--

DROP TABLE IF EXISTS `marriages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `marriages` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `chat_id` bigint NOT NULL,
  `user1_id` bigint NOT NULL,
  `user2_id` bigint NOT NULL,
  `married_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_pair` (`chat_id`,`user1_id`,`user2_id`),
  KEY `idx_marriage_user1` (`chat_id`,`user1_id`),
  KEY `idx_marriage_user2` (`chat_id`,`user2_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `marriages`
--

LOCK TABLES `marriages` WRITE;
/*!40000 ALTER TABLE `marriages` DISABLE KEYS */;
INSERT INTO `marriages` VALUES (1,-1003673552861,7790517846,8759004874,'2026-07-12 18:04:26'),(2,-1003673552861,5242991121,8114583471,'2026-07-12 18:09:29'),(3,-1003673552861,8037189102,8509346376,'2026-07-13 19:54:18');
/*!40000 ALTER TABLE `marriages` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `message_daily`
--

DROP TABLE IF EXISTS `message_daily`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `message_daily` (
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `day` date NOT NULL,
  `message_count` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`chat_id`,`user_id`,`day`),
  KEY `idx_message_daily_chat_day` (`chat_id`,`day`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `message_daily`
--

LOCK TABLES `message_daily` WRITE;
/*!40000 ALTER TABLE `message_daily` DISABLE KEYS */;
INSERT INTO `message_daily` VALUES (-1004315708356,8114583471,'2026-07-13',55),(-1004315708356,8114583471,'2026-07-14',68),(-1003811995090,5242991121,'2026-07-13',7),(-1003811995090,5242991121,'2026-07-14',3),(-1003811995090,5242991121,'2026-07-15',6),(-1003811995090,5707066924,'2026-07-13',2),(-1003811995090,5707066924,'2026-07-14',85),(-1003811995090,7547410082,'2026-07-14',75),(-1003811995090,7547410082,'2026-07-15',1),(-1003811995090,7790517846,'2026-07-13',6),(-1003811995090,7790517846,'2026-07-14',39),(-1003811995090,7790517846,'2026-07-15',2),(-1003811995090,8114583471,'2026-07-13',31),(-1003811995090,8114583471,'2026-07-14',110),(-1003811995090,8114583471,'2026-07-15',10),(-1003811995090,8407034059,'2026-07-14',7),(-1003811995090,8759004874,'2026-07-13',3),(-1003811995090,8759004874,'2026-07-14',5),(-1003673552861,1307190691,'2026-07-16',9),(-1003673552861,1312624847,'2026-07-15',242),(-1003673552861,1475524466,'2026-07-13',57),(-1003673552861,1475524466,'2026-07-14',127),(-1003673552861,1475524466,'2026-07-15',8),(-1003673552861,1475524466,'2026-07-16',3),(-1003673552861,1508737016,'2026-07-14',24),(-1003673552861,1508737016,'2026-07-15',122),(-1003673552861,1984456868,'2026-07-13',30),(-1003673552861,1984456868,'2026-07-14',37),(-1003673552861,1984456868,'2026-07-15',18),(-1003673552861,1984456868,'2026-07-16',4),(-1003673552861,5080664830,'2026-07-13',39),(-1003673552861,5080664830,'2026-07-14',107),(-1003673552861,5080664830,'2026-07-15',41),(-1003673552861,5080664830,'2026-07-16',9),(-1003673552861,5238563460,'2026-07-13',30),(-1003673552861,5238563460,'2026-07-14',45),(-1003673552861,5238563460,'2026-07-15',6),(-1003673552861,5238563460,'2026-07-16',7),(-1003673552861,5242991121,'2026-07-13',205),(-1003673552861,5242991121,'2026-07-14',153),(-1003673552861,5242991121,'2026-07-15',368),(-1003673552861,5242991121,'2026-07-16',17),(-1003673552861,5400209637,'2026-07-16',5),(-1003673552861,5707066924,'2026-07-13',67),(-1003673552861,5707066924,'2026-07-14',194),(-1003673552861,5707066924,'2026-07-15',149),(-1003673552861,5707066924,'2026-07-16',32),(-1003673552861,5771975148,'2026-07-13',17),(-1003673552861,5771975148,'2026-07-14',62),(-1003673552861,5771975148,'2026-07-15',1),(-1003673552861,5918411165,'2026-07-14',2),(-1003673552861,5918411165,'2026-07-15',7),(-1003673552861,5918411165,'2026-07-16',2),(-1003673552861,6105651374,'2026-07-13',8),(-1003673552861,6542960747,'2026-07-13',19),(-1003673552861,6542960747,'2026-07-14',7),(-1003673552861,6542960747,'2026-07-15',73),(-1003673552861,6723156345,'2026-07-13',3),(-1003673552861,6881601407,'2026-07-14',237),(-1003673552861,7329106105,'2026-07-15',7),(-1003673552861,7547410082,'2026-07-13',117),(-1003673552861,7547410082,'2026-07-14',190),(-1003673552861,7547410082,'2026-07-15',150),(-1003673552861,7547410082,'2026-07-16',4),(-1003673552861,7579895039,'2026-07-14',8),(-1003673552861,7790517846,'2026-07-13',169),(-1003673552861,7790517846,'2026-07-14',188),(-1003673552861,7790517846,'2026-07-15',101),(-1003673552861,7790517846,'2026-07-16',30),(-1003673552861,7982777490,'2026-07-13',3),(-1003673552861,7982777490,'2026-07-14',17),(-1003673552861,7982777490,'2026-07-15',3),(-1003673552861,8037189102,'2026-07-13',83),(-1003673552861,8037189102,'2026-07-14',62),(-1003673552861,8037189102,'2026-07-15',9),(-1003673552861,8114583471,'2026-07-13',75),(-1003673552861,8114583471,'2026-07-14',301),(-1003673552861,8114583471,'2026-07-15',129),(-1003673552861,8114583471,'2026-07-16',28),(-1003673552861,8149834084,'2026-07-13',47),(-1003673552861,8149834084,'2026-07-14',61),(-1003673552861,8149834084,'2026-07-15',10),(-1003673552861,8176377509,'2026-07-15',299),(-1003673552861,8265845625,'2026-07-16',12),(-1003673552861,8288451562,'2026-07-13',53),(-1003673552861,8288451562,'2026-07-14',29),(-1003673552861,8288451562,'2026-07-15',1),(-1003673552861,8288451562,'2026-07-16',3),(-1003673552861,8407034059,'2026-07-13',1),(-1003673552861,8407034059,'2026-07-14',11),(-1003673552861,8407034059,'2026-07-15',2),(-1003673552861,8509346376,'2026-07-13',91),(-1003673552861,8509346376,'2026-07-14',40),(-1003673552861,8509346376,'2026-07-16',2),(-1003673552861,8650988494,'2026-07-13',2),(-1003673552861,8700500174,'2026-07-13',68),(-1003673552861,8700500174,'2026-07-14',36),(-1003673552861,8700500174,'2026-07-15',14),(-1003673552861,8700500174,'2026-07-16',5),(-1003673552861,8759004874,'2026-07-13',102),(-1003673552861,8759004874,'2026-07-14',82),(-1003673552861,8759004874,'2026-07-15',2),(-1003673552861,8759004874,'2026-07-16',5);
/*!40000 ALTER TABLE `message_daily` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `message_stats`
--

DROP TABLE IF EXISTS `message_stats`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `message_stats` (
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `message_count` bigint unsigned NOT NULL DEFAULT '0',
  `first_seen_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `last_message_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_id`,`user_id`),
  KEY `idx_stats_leaderboard` (`chat_id`,`message_count` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `message_stats`
--

LOCK TABLES `message_stats` WRITE;
/*!40000 ALTER TABLE `message_stats` DISABLE KEYS */;
INSERT INTO `message_stats` VALUES (-1004315708356,8114583471,131,'2026-07-12 15:05:40','2026-07-14 19:11:38'),(-1003811995090,5242991121,16,'2026-07-13 11:22:49','2026-07-15 18:44:21'),(-1003811995090,5707066924,88,'2026-07-12 15:28:53','2026-07-14 23:32:03'),(-1003811995090,7547410082,76,'2026-07-14 03:19:36','2026-07-15 18:38:05'),(-1003811995090,7790517846,58,'2026-07-12 15:25:27','2026-07-15 18:43:19'),(-1003811995090,8114583471,176,'2026-07-12 15:19:13','2026-07-15 18:39:02'),(-1003811995090,8407034059,15,'2026-07-12 15:18:31','2026-07-14 10:28:31'),(-1003811995090,8759004874,9,'2026-07-12 16:03:50','2026-07-14 20:18:29'),(-1003673552861,1307190691,9,'2026-07-16 13:26:53','2026-07-16 14:00:49'),(-1003673552861,1312624847,242,'2026-07-15 18:27:23','2026-07-15 20:42:59'),(-1003673552861,1475524466,195,'2026-07-13 16:45:37','2026-07-16 14:51:17'),(-1003673552861,1508737016,146,'2026-07-14 03:12:37','2026-07-15 20:19:31'),(-1003673552861,1984456868,102,'2026-07-12 15:15:55','2026-07-16 13:18:41'),(-1003673552861,5080664830,229,'2026-07-12 18:37:49','2026-07-16 15:26:35'),(-1003673552861,5238563460,88,'2026-07-13 20:52:36','2026-07-16 15:04:56'),(-1003673552861,5242991121,827,'2026-07-12 14:59:45','2026-07-16 15:37:19'),(-1003673552861,5248704461,5,'2026-07-12 15:11:37','2026-07-12 15:21:47'),(-1003673552861,5400209637,5,'2026-07-16 15:24:08','2026-07-16 15:26:52'),(-1003673552861,5707066924,481,'2026-07-12 14:59:45','2026-07-16 15:09:42'),(-1003673552861,5771975148,107,'2026-07-12 15:22:17','2026-07-15 18:10:28'),(-1003673552861,5918411165,11,'2026-07-14 10:35:20','2026-07-16 15:38:23'),(-1003673552861,6105651374,11,'2026-07-13 08:23:48','2026-07-13 20:01:10'),(-1003673552861,6542960747,115,'2026-07-13 06:14:57','2026-07-15 19:46:56'),(-1003673552861,6723156345,3,'2026-07-13 22:36:46','2026-07-13 22:36:56'),(-1003673552861,6881601407,237,'2026-07-14 08:37:29','2026-07-14 19:35:19'),(-1003673552861,7329106105,7,'2026-07-15 11:07:48','2026-07-15 11:13:28'),(-1003673552861,7547410082,503,'2026-07-12 17:44:32','2026-07-16 15:14:04'),(-1003673552861,7579895039,37,'2026-07-12 18:18:26','2026-07-14 08:41:24'),(-1003673552861,7790517846,655,'2026-07-12 14:57:42','2026-07-16 14:59:31'),(-1003673552861,7982777490,59,'2026-07-12 18:36:20','2026-07-15 19:11:00'),(-1003673552861,8037189102,180,'2026-07-12 18:00:06','2026-07-15 15:04:36'),(-1003673552861,8114583471,624,'2026-07-12 14:59:45','2026-07-16 15:14:04'),(-1003673552861,8149834084,153,'2026-07-12 15:09:55','2026-07-15 19:47:15'),(-1003673552861,8176377509,299,'2026-07-15 19:28:19','2026-07-15 20:46:48'),(-1003673552861,8265845625,12,'2026-07-16 13:58:49','2026-07-16 15:25:42'),(-1003673552861,8288451562,86,'2026-07-13 11:22:55','2026-07-16 14:55:05'),(-1003673552861,8407034059,22,'2026-07-12 15:01:23','2026-07-15 17:32:25'),(-1003673552861,8509346376,133,'2026-07-13 19:50:53','2026-07-16 15:37:04'),(-1003673552861,8650988494,2,'2026-07-13 11:27:33','2026-07-13 11:27:37'),(-1003673552861,8700500174,141,'2026-07-12 15:32:49','2026-07-16 15:37:05'),(-1003673552861,8759004874,280,'2026-07-12 15:39:03','2026-07-16 15:04:37');
/*!40000 ALTER TABLE `message_stats` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `mutes`
--

DROP TABLE IF EXISTS `mutes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `mutes` (
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `muted_by` bigint NOT NULL,
  `muted_until` datetime DEFAULT NULL,
  `reason` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_id`,`user_id`),
  KEY `idx_mutes_until` (`muted_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `mutes`
--

LOCK TABLES `mutes` WRITE;
/*!40000 ALTER TABLE `mutes` DISABLE KEYS */;
INSERT INTO `mutes` VALUES (-1003811995090,8114583471,7790517846,'2026-07-14 10:32:10',NULL,'2026-07-14 10:29:14');
/*!40000 ALTER TABLE `mutes` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `nicknames`
--

DROP TABLE IF EXISTS `nicknames`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `nicknames` (
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `nickname` varchar(64) NOT NULL,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_id`,`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `nicknames`
--

LOCK TABLES `nicknames` WRITE;
/*!40000 ALTER TABLE `nicknames` DISABLE KEYS */;
INSERT INTO `nicknames` VALUES (-1004315708356,8114583471,'хуйлан','2026-07-13 12:48:23'),(-1003673552861,1508737016,'Йесраель Йигурда','2026-07-14 17:56:53'),(-1003673552861,5238563460,'Линочка','2026-07-13 21:08:53'),(-1003673552861,5242991121,'алкоголизм','2026-07-14 07:31:23'),(-1003673552861,7790517846,'мурзик ористократ','2026-07-12 18:05:23'),(-1003673552861,8114583471,'хуйло','2026-07-14 07:31:53'),(-1003673552861,8509346376,'Маринка Макинами','2026-07-13 21:08:36');
/*!40000 ALTER TABLE `nicknames` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `profile_cards`
--

DROP TABLE IF EXISTS `profile_cards`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `profile_cards` (
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `title` varchar(30) DEFAULT NULL,
  `motto` varchar(100) DEFAULT NULL,
  `is_citizen` tinyint(1) NOT NULL DEFAULT '0',
  `gender` enum('Ð¼','Ð¶','Ð´Ñ€') DEFAULT NULL,
  `city` varchar(64) DEFAULT NULL,
  `about_text` varchar(1000) DEFAULT NULL,
  `anketa_visible` tinyint(1) NOT NULL DEFAULT '1',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`chat_id`,`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `profile_cards`
--

LOCK TABLES `profile_cards` WRITE;
/*!40000 ALTER TABLE `profile_cards` DISABLE KEYS */;
/*!40000 ALTER TABLE `profile_cards` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `relationship_requests`
--

DROP TABLE IF EXISTS `relationship_requests`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `relationship_requests` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `chat_id` bigint NOT NULL,
  `from_user_id` bigint NOT NULL,
  `to_user_id` bigint NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_relreq_to` (`chat_id`,`to_user_id`,`created_at` DESC),
  KEY `idx_relreq_from` (`chat_id`,`from_user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `relationship_requests`
--

LOCK TABLES `relationship_requests` WRITE;
/*!40000 ALTER TABLE `relationship_requests` DISABLE KEYS */;
INSERT INTO `relationship_requests` VALUES (1,-1003673552861,7790517846,8759004874,'2026-07-12 18:06:40'),(3,-1003673552861,8509346376,5238563460,'2026-07-13 20:53:44');
/*!40000 ALTER TABLE `relationship_requests` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `relationships`
--

DROP TABLE IF EXISTS `relationships`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `relationships` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `chat_id` bigint NOT NULL,
  `user1_id` bigint NOT NULL,
  `user2_id` bigint NOT NULL,
  `points` bigint NOT NULL DEFAULT '0',
  `level` tinyint unsigned NOT NULL DEFAULT '0',
  `started_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `last_action_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_relationship_pair` (`chat_id`,`user1_id`,`user2_id`),
  KEY `idx_relationship_user1` (`chat_id`,`user1_id`),
  KEY `idx_relationship_user2` (`chat_id`,`user2_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `relationships`
--

LOCK TABLES `relationships` WRITE;
/*!40000 ALTER TABLE `relationships` DISABLE KEYS */;
/*!40000 ALTER TABLE `relationships` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `request_messages`
--

DROP TABLE IF EXISTS `request_messages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `request_messages` (
  `message_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `is_anchor` tinyint(1) NOT NULL DEFAULT '0',
  `status` enum('pending','accepted','rejected') NOT NULL DEFAULT 'pending',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `decided_by` bigint DEFAULT NULL,
  `decided_at` datetime DEFAULT NULL,
  PRIMARY KEY (`message_id`),
  KEY `idx_request_user` (`user_id`),
  KEY `idx_request_anchor` (`user_id`,`is_anchor`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `request_messages`
--

LOCK TABLES `request_messages` WRITE;
/*!40000 ALTER TABLE `request_messages` DISABLE KEYS */;
INSERT INTO `request_messages` VALUES (8964,8114583471,1,'accepted','2026-07-12 15:21:14',7790517846,'2026-07-12 15:21:29'),(9015,8759004874,1,'rejected','2026-07-12 16:03:34',8114583471,'2026-07-12 16:03:57'),(9093,8114583471,0,'pending','2026-07-13 21:20:43',NULL,NULL),(9094,8114583471,0,'pending','2026-07-13 21:20:48',NULL,NULL),(9308,8114583471,0,'pending','2026-07-14 11:16:53',NULL,NULL),(177775,5242991121,1,'rejected','2026-07-12 15:03:52',7790517846,'2026-07-12 15:04:03'),(177777,5242991121,0,'pending','2026-07-12 15:03:58',NULL,NULL),(177780,5242991121,0,'pending','2026-07-12 15:04:08',NULL,NULL),(177781,5242991121,0,'pending','2026-07-12 15:04:08',NULL,NULL),(177783,5242991121,0,'pending','2026-07-12 15:04:18',NULL,NULL),(177787,5242991121,0,'pending','2026-07-12 15:04:27',NULL,NULL),(177788,5242991121,0,'pending','2026-07-12 15:04:28',NULL,NULL),(177790,5242991121,0,'pending','2026-07-12 15:04:30',NULL,NULL),(177793,5242991121,0,'pending','2026-07-12 15:04:37',NULL,NULL),(177794,5242991121,0,'pending','2026-07-12 15:05:01',NULL,NULL),(177798,5242991121,0,'pending','2026-07-12 15:05:24',NULL,NULL),(177805,5242991121,0,'pending','2026-07-12 15:05:47',NULL,NULL);
/*!40000 ALTER TABLE `request_messages` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `rest_requests`
--

DROP TABLE IF EXISTS `rest_requests`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `rest_requests` (
  `id` int NOT NULL AUTO_INCREMENT,
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `duration_seconds` bigint NOT NULL,
  `reason` varchar(500) DEFAULT NULL,
  `status` enum('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  `requested_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `decided_by` bigint DEFAULT NULL,
  `decided_at` timestamp NULL DEFAULT NULL,
  `expires_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_rest_chat_user` (`chat_id`,`user_id`),
  KEY `idx_rest_status` (`chat_id`,`status`,`expires_at`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `rest_requests`
--

LOCK TABLES `rest_requests` WRITE;
/*!40000 ALTER TABLE `rest_requests` DISABLE KEYS */;
INSERT INTO `rest_requests` VALUES (1,-1003673552861,8114583471,172800,'я хуйло','rejected','2026-07-13 21:22:58',8114583471,'2026-07-13 21:23:08',NULL),(2,-1003673552861,8114583471,86400,'устал','rejected','2026-07-13 21:42:09',8114583471,'2026-07-13 21:42:33',NULL),(3,-1003673552861,8114583471,10800,'дайте отдых паже','approved','2026-07-14 08:29:29',8114583471,'2026-07-14 08:30:51','2026-07-14 11:30:51'),(4,-1003673552861,8114583471,604800,'идитенахуй я чилить','approved','2026-07-14 16:27:11',5707066924,'2026-07-14 17:02:59','2026-07-21 17:02:59'),(5,-1003673552861,5707066924,10800,'я голодоранец','rejected','2026-07-14 23:19:38',5707066924,'2026-07-14 23:19:43',NULL),(6,-1003673552861,8037189102,1209600,'мненадо очень','approved','2026-07-14 23:31:07',5707066924,'2026-07-14 23:31:23','2026-07-28 23:31:23'),(7,-1003673552861,5242991121,2592000,'лагер.','approved','2026-07-15 18:38:50',7790517846,'2026-07-15 18:40:13','2026-08-14 18:40:13');
/*!40000 ALTER TABLE `rest_requests` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `reward_degree_levels`
--

DROP TABLE IF EXISTS `reward_degree_levels`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `reward_degree_levels` (
  `degree` tinyint unsigned NOT NULL,
  `min_level` tinyint NOT NULL,
  `updated_by` bigint DEFAULT NULL,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`degree`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `reward_degree_levels`
--

LOCK TABLES `reward_degree_levels` WRITE;
/*!40000 ALTER TABLE `reward_degree_levels` DISABLE KEYS */;
/*!40000 ALTER TABLE `reward_degree_levels` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `rewards`
--

DROP TABLE IF EXISTS `rewards`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `rewards` (
  `id` int NOT NULL AUTO_INCREMENT,
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `degree` tinyint unsigned NOT NULL,
  `reason` varchar(500) DEFAULT NULL,
  `awarded_by` bigint NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_rewards_chat_user` (`chat_id`,`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `rewards`
--

LOCK TABLES `rewards` WRITE;
/*!40000 ALTER TABLE `rewards` DISABLE KEYS */;
INSERT INTO `rewards` VALUES (1,-1003673552861,8114583471,7,'иба клева бот слышь гавнюк',7790517846,'2026-07-12 15:04:22'),(2,-1003673552861,8759004874,5,'пес',7790517846,'2026-07-13 08:15:24'),(3,-1003673552861,7790517846,8,'глова',8114583471,'2026-07-13 08:16:53'),(4,-1003673552861,8114583471,2,'Лучший',7547410082,'2026-07-14 16:21:25'),(5,-1003673552861,5771975148,3,'слей девушка',8114583471,'2026-07-14 18:18:09'),(6,-1003673552861,8176377509,1,'дендрофил',8114583471,'2026-07-15 19:55:09');
/*!40000 ALTER TABLE `rewards` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `settings`
--

DROP TABLE IF EXISTS `settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `settings` (
  `id` tinyint unsigned NOT NULL DEFAULT '1',
  `notify_chat_id` bigint DEFAULT NULL,
  `notify_topic_id` bigint DEFAULT NULL,
  `invite_link` varchar(512) DEFAULT NULL,
  `welcome_message` text,
  `link_message_template` text,
  `reject_message` text,
  `complaint_chat_id` bigint DEFAULT NULL,
  `level_names` text,
  `admin_icon` varchar(16) DEFAULT NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `chk_settings_single_row` CHECK ((`id` = 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `settings`
--

LOCK TABLES `settings` WRITE;
/*!40000 ALTER TABLE `settings` DISABLE KEYS */;
INSERT INTO `settings` VALUES (1,-1003811995090,NULL,'https://t.me/+6w93LlpmRaM5ZjRi',NULL,NULL,NULL,-1003673552861,NULL,NULL);
/*!40000 ALTER TABLE `settings` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `test_mode_admins`
--

DROP TABLE IF EXISTS `test_mode_admins`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `test_mode_admins` (
  `user_id` bigint NOT NULL,
  `enabled_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `test_mode_admins`
--

LOCK TABLES `test_mode_admins` WRITE;
/*!40000 ALTER TABLE `test_mode_admins` DISABLE KEYS */;
/*!40000 ALTER TABLE `test_mode_admins` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `timers`
--

DROP TABLE IF EXISTS `timers`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `timers` (
  `id` int NOT NULL AUTO_INCREMENT,
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `fire_at` datetime NOT NULL,
  `text` text NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_timers_chat` (`chat_id`),
  KEY `idx_timers_fire_at` (`fire_at`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `timers`
--

LOCK TABLES `timers` WRITE;
/*!40000 ALTER TABLE `timers` DISABLE KEYS */;
/*!40000 ALTER TABLE `timers` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `warns`
--

DROP TABLE IF EXISTS `warns`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `warns` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `chat_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `warned_by` bigint NOT NULL,
  `reason` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_warns_user` (`chat_id`,`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `warns`
--

LOCK TABLES `warns` WRITE;
/*!40000 ALTER TABLE `warns` DISABLE KEYS */;
INSERT INTO `warns` VALUES (1,-1003673552861,8759004874,5242991121,NULL,'2026-07-13 11:19:32'),(2,-1003673552861,5707066924,7790517846,NULL,'2026-07-13 11:19:40');
/*!40000 ALTER TABLE `warns` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-07-16 15:45:08
